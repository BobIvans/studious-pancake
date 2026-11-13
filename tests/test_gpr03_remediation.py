"""GPR-03 measured-blocker remediation tests. Offline fixtures only.

Covers: the deployed GraphQL Content-Length rejection replay and its bounded
transport fix (request parity guard + missing/malformed/chunked response
tolerance without weakened caps), the narrowed Aftermath bounded profile, the
typed two-provider checkpoint binding contract with its live BLOCKED verdict,
and the package-bound Move decoder contracts with positive/negative fixtures.
Fixture bytes are test contracts, never mainnet qualification or live reads.
"""

import asyncio
import base64
from dataclasses import replace
import json
from pathlib import Path

import httpx
import pytest

from src.gpr_sui_shadow.bcs import metadata_decimals, parse_move_type
from src.gpr_sui_shadow.campaign import default_profiles
from src.gpr_sui_shadow.decoders import (
    POOL_DECODER_LAYOUT,
    REVIEWED_FEE_SEMANTICS,
    DeepBookPoolDecoder,
    decode_bcs_u64_fields,
)
from src.gpr_sui_shadow.intake import (
    CapturedJsonTransport,
    SuiIntakePlane,
    validate_capture,
)
from src.gpr_sui_shadow.providers import (
    CheckpointConsistencyEvidence,
    CheckpointProviderBinding,
    LIVE_SUI_PROVIDERS_BLOCKED,
    live_binding_verdict,
    verify_offline_pair,
)
from src.gpr_sui_shadow.sources import (
    PoolIndexAdapter,
    aftermath_pools_request,
    checkpoint_request,
)
from src.market.streams import RecoverableStreamJournal
from src.provider_governance import ProviderGovernance
from src.qualification_campaign.evidence import CampaignEvidenceStore
from src.qualification_campaign.identity import CampaignManifest, digest
from src.routing.transport import (
    HttpxJsonTransport,
    SanitizedTransportError,
    TransportPolicy,
    decide_response_content_length,
)
from tests.test_gpr03_sui_shadow import (
    NOW,
    REVIEWED_PACKAGE,
    candidate_for,
    corpus,
    metadata_bcs,
    object_payload,
    pool_state_bcs,
    profile,
    uleb128,
)

RECORDED_GRAPHQL_REJECTION = b"Header of type `content-length` was missing"
RECORDED_REQUEST_BODY_BYTES = 123


def plane_for(tmp_path, p, handler):
    registry, seed = corpus()
    evidence = CampaignEvidenceStore(
        RecoverableStreamJournal(tmp_path / "events.sqlite"),
        CampaignManifest(
            "a" * 40,
            "b" * 40,
            "c" * 64,
            (("gpr.registry", registry.generation), ("gpr.seed", seed.generation)),
            ((p.profile_id, p.generation),),
        ),
        wall_ns=lambda: NOW,
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False)
    transport = CapturedJsonTransport(
        policy=TransportPolicy(max_attempts=1),
        allowed_hosts={p.hostname},
        client=client,
    )
    gov = ProviderGovernance(
        {p.profile_id: p.entitlement(2000)}, clock=lambda: 1002, wall_clock=lambda: 1002
    )
    return (
        SuiIntakePlane(gov, transport, evidence, wall_ns=lambda: NOW),
        client,
        evidence,
    )


def pins():
    return json.loads(Path("config/gpr03_sui_source_pins.json").read_text())


# ---------------------------------------------------------------------------
# Recorded GraphQL Content-Length rejection: bounded transport fix
# ---------------------------------------------------------------------------


def test_recorded_graphql_rejection_replays_with_complete_wire_evidence(tmp_path):
    """The deployed 400/43-byte text rejection replays offline, fails closed,
    and retains the exact 123-byte request proof with declared length parity."""
    p = profile(1)

    def handler(req):
        return httpx.Response(
            400,
            content=RECORDED_GRAPHQL_REJECTION,
            headers={"content-type": "text/plain"},
        )

    async def run():
        intake, client, evidence = plane_for(tmp_path, p, handler)
        ref, raw = await intake.collect(p, checkpoint_request(p.endpoint))
        await client.aclose()
        return ref, raw, evidence

    ref, raw, evidence = asyncio.run(run())
    sent = base64.b64decode(raw["request_wire_base64"], validate=True)
    assert raw["http_status"] == 400 and raw["quality"] == "transport-error"
    assert raw["failure_reason"] == "provider returned invalid content type"
    # The issued request proof: exactly the recorded 123-byte body whose
    # declared Content-Length equals the actual wire body, byte for byte.
    assert raw["sent_content_length"] == str(RECORDED_REQUEST_BODY_BYTES)
    assert raw["request_wire_bytes"] == RECORDED_REQUEST_BODY_BYTES == len(sent)
    assert sent == checkpoint_request(p.endpoint).serialized_body
    # The negative 43-byte response is fully captured with a typed reason and
    # no inferred payload, candidates or retry.
    body = base64.b64decode(raw["wire_payload_base64"], validate=True)
    assert body == RECORDED_GRAPHQL_REJECTION
    assert raw["body_capture_complete"] is True
    assert raw["raw_payload"] is None and raw["response_hash"] is None
    assert not any(
        r.get("kind") in ("gpr03_sui_candidate", "gpr03_structural_rate")
        for r in evidence.replay()
    )
    validate_capture(evidence, ref)


@pytest.mark.parametrize("declared", ["", "abc", "12, 34", " 12", "+12", "1_2", "0x10"])
def test_malformed_response_content_length_is_tolerated_and_captured(
    tmp_path, declared
):
    """A malformed declared length never blocks capture: streamed caps bound
    the body, the mode is recorded, and the typed reason still fails closed."""
    p = profile(1)

    def handler(req):
        return httpx.Response(
            400,
            content=RECORDED_GRAPHQL_REJECTION,
            headers={"content-type": "text/plain", "content-length": declared},
        )

    async def run():
        intake, client, _ = plane_for(tmp_path, p, handler)
        _, raw = await intake.collect(p, checkpoint_request(p.endpoint))
        await client.aclose()
        return raw

    raw = asyncio.run(run())
    assert raw["content_length_mode"] == "malformed-ignored"
    assert raw["body_capture_complete"] is True
    assert raw["wire_payload_bytes"] == len(RECORDED_GRAPHQL_REJECTION)
    assert raw["quality"] == "transport-error"
    assert raw["failure_reason"] == "provider returned invalid content type"


def test_response_content_length_modes_are_recorded_and_tolerated(tmp_path):
    """Valid-declared and chunked-framed responses are bounded by the streamed
    caps, never by the untrusted header; both modes are retained in the
    capture (a truly absent header is covered by the decision unit test)."""
    p = profile(1)
    payload = object_payload(candidate_for(*corpus()))

    async def run():
        results = []
        for headers in (
            {"content-type": "application/json"},  # auto-set valid content-length
            {  # chunked framing with an untrusted content-length also present
                "content-type": "application/json",
                "transfer-encoding": "chunked",
                "content-length": "999999",
            },
        ):
            intake, client, _ = plane_for(
                tmp_path,
                p,
                lambda req, headers=headers: httpx.Response(
                    200, json=payload, headers=headers
                ),
            )
            _, raw = await intake.collect(p, checkpoint_request(p.endpoint))
            await client.aclose()
            results.append(raw)
        return results

    declared, chunked = asyncio.run(run())
    assert declared["content_length_mode"] == "within-cap"
    assert declared["quality"] == "accepted-read-only"
    assert chunked["content_length_mode"] == "chunked-ignored"
    assert chunked["quality"] == "accepted-read-only"
    assert chunked["declared_transfer_encoding"] == "chunked"


def test_declared_oversized_content_length_still_fails_closed_before_read(tmp_path):
    p = profile(1)

    def handler(req):
        return httpx.Response(
            200,
            content=b"{}",
            headers={"content-type": "application/json", "content-length": "2097152"},
        )

    async def run():
        intake, client, _ = plane_for(tmp_path, p, handler)
        _, raw = await intake.collect(p, checkpoint_request(p.endpoint))
        await client.aclose()
        return raw

    raw = asyncio.run(run())
    assert raw["quality"] == "transport-error"
    assert raw["failure_reason"] == "provider response body too large"
    assert raw["body_capture_complete"] is False


def test_streamed_oversized_payload_without_content_length_fails_closed(tmp_path):
    p = profile(1)
    total = 1_048_576 + 1

    async def gen():
        remaining = total
        while remaining:
            piece = min(4096, remaining)
            remaining -= piece
            yield b"a" * piece

    def handler(req):
        return httpx.Response(
            200, content=gen(), headers={"content-type": "application/json"}
        )

    async def run():
        intake, client, _ = plane_for(tmp_path, p, handler)
        _, raw = await intake.collect(p, checkpoint_request(p.endpoint))
        await client.aclose()
        return raw

    raw = asyncio.run(run())
    assert raw["quality"] == "transport-error"
    assert raw["failure_reason"] == "provider response wire body too large"
    # httpx frames generator content with transfer-encoding; the untrusted
    # content-length is ignored and the streamed wire cap still fails closed.
    assert raw["content_length_mode"] == "chunked-ignored"


def test_request_content_length_parity_violation_fails_closed_before_send():
    """A declared request Content-Length that disagrees with the built body is
    rejected before any bytes are sent; the transport never rewrites it."""
    seen = []

    def handler(req):
        seen.append(req)
        return httpx.Response(
            200, json={}, headers={"content-type": "application/json"}
        )

    async def run():
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), trust_env=False
        )
        transport = HttpxJsonTransport(
            policy=TransportPolicy(max_attempts=1),
            allowed_hosts={"graphql.mainnet.sui.io"},
            client=client,
        )
        try:
            with pytest.raises(
                SanitizedTransportError, match="content-length parity violation"
            ):
                await transport.request(
                    "POST",
                    "https://graphql.mainnet.sui.io/graphql",
                    headers={
                        "Content-Length": "999",
                        "Content-Type": "application/json",
                    },
                    json_body={"query": "x"},
                )
        finally:
            await client.aclose()

    asyncio.run(run())
    assert seen == []


def test_decide_response_content_length_modes():
    cap = 1_048_576
    absent = decide_response_content_length(None, transfer_encoding=None, cap=cap)
    assert absent.mode == "absent" and absent.declared is None
    chunked = decide_response_content_length("5", transfer_encoding="chunked", cap=cap)
    assert chunked.mode == "chunked-ignored" and chunked.declared is None
    malformed = decide_response_content_length(
        "12, 34", transfer_encoding=None, cap=cap
    )
    assert malformed.mode == "malformed-ignored" and malformed.declared is None
    within = decide_response_content_length("1048576", transfer_encoding=None, cap=cap)
    assert within.mode == "within-cap" and within.declared == 1_048_576
    over = decide_response_content_length("1048577", transfer_encoding=None, cap=cap)
    assert over.mode == "over-cap" and over.declared == 1_048_577
    implausible = decide_response_content_length(
        "9" * 21, transfer_encoding=None, cap=cap
    )
    assert implausible.mode == "over-cap"


# ---------------------------------------------------------------------------
# Narrowed Aftermath bounded profile
# ---------------------------------------------------------------------------


def test_aftermath_profile_is_narrowed_and_request_shape_is_pinned():
    profiles = default_profiles(pins())
    aftermath = next(p for p in profiles if p.source_kind == "aftermath")
    narrowed = pins()["aftermath"]["narrowed_profile"]
    assert aftermath.max_response_bytes == narrowed["max_response_bytes"] == 1_048_576
    assert aftermath.max_json_nodes == narrowed["max_json_nodes"] == 20_000
    request = aftermath_pools_request(aftermath.endpoint)
    assert request.serialized_body == b"{}"
    assert request.method == "POST" and request.purpose == "pool-index"


def test_aftermath_narrowed_profile_cannot_be_re_expanded_by_config_drift():
    drifted_pins = {
        **pins(),
        "aftermath": {
            **pins()["aftermath"],
            "narrowed_profile": {
                **pins()["aftermath"]["narrowed_profile"],
                "max_response_bytes": 2_097_152,
            },
        },
    }
    with pytest.raises(ValueError, match="NARROWED_PROFILE"):
        default_profiles(drifted_pins)


def test_aftermath_row_scan_cap_is_respected_with_truncation_evidence(tmp_path):
    p = replace(profile(1, "aftermath"), method="POST")
    registry, seed = corpus()
    candidate = candidate_for(registry, seed)
    rows = [
        {
            "coins": {candidate.coin_types[0]: 1, candidate.coin_types[1]: 1},
            "objectId": "0x" + format(index, "064x"),
        }
        for index in range(600)
    ]

    def handler(req):
        assert req.headers["content-length"] == "2"  # pinned {} request body
        return httpx.Response(
            200, json=rows, headers={"content-type": "application/json"}
        )

    async def run():
        intake, client, _ = plane_for(tmp_path, p, handler)
        _, raw = await intake.collect(
            p, aftermath_pools_request(p.endpoint), PoolIndexAdapter("aftermath")
        )
        await client.aclose()
        return raw

    raw = asyncio.run(run())
    assert raw["quality"] == "accepted"
    assert raw["rejections"] == {"bounded-row-scan-truncated": 88}
    assert raw["http_status"] == 200 and raw["content_length_mode"] == "within-cap"


@pytest.mark.parametrize(
    "mode", ["declared-over-cap", "wire-over-cap", "json-node-over-cap"]
)
def test_aftermath_oversized_response_fails_closed_with_typed_reason(tmp_path, mode):
    p = replace(profile(1, "aftermath"), method="POST")

    async def gen():
        for _ in range(300):
            yield b"a" * 4096

    if mode == "declared-over-cap":

        def handler(req):
            return httpx.Response(
                200,
                content=b"{}",
                headers={
                    "content-type": "application/json",
                    "content-length": "2097152",
                },
            )

    elif mode == "wire-over-cap":

        def handler(req):
            return httpx.Response(
                200, content=gen(), headers={"content-type": "application/json"}
            )

    else:

        def nested(depth):
            if depth == 0:
                return 1
            return [nested(depth - 1), nested(depth - 1)]

        def handler(req):
            # Depth-bounded binary tree: each container is small, but the total
            # node count exceeds the 20,000-node profile cap (preflight typed).
            return httpx.Response(
                200,
                json={"data": nested(16)},
                headers={"content-type": "application/json"},
            )

    async def run():
        intake, client, evidence = plane_for(tmp_path, p, handler)
        _, raw = await intake.collect(
            p, aftermath_pools_request(p.endpoint), PoolIndexAdapter("aftermath")
        )
        await client.aclose()
        return raw, evidence

    raw, evidence = asyncio.run(run())
    expected = {
        "declared-over-cap": "provider response body too large",
        "wire-over-cap": "provider response wire body too large",
        "json-node-over-cap": "provider JSON node limit exceeded",
    }
    assert raw["quality"] == "transport-error"
    assert raw["failure_reason"] == expected[mode]
    assert raw["http_status"] == 200
    assert raw["physical_attempt_started"] is True
    assert not any(r.get("kind") == "gpr03_sui_candidate" for r in evidence.replay())


# ---------------------------------------------------------------------------
# Typed two-provider checkpoint binding contract
# ---------------------------------------------------------------------------


def binding_for_profile(p, transport):
    return CheckpointProviderBinding(
        profile_id=p.profile_id,
        provider=p.provider,
        operator=p.operator,
        correlation_group=p.correlation_group,
        transport=transport,
        endpoint=p.endpoint,
        schema_pin="a" * 64,
        genesis_chain_identifier="reviewed-fixture-mainnet-id",
    )


def capture_bindings_from_profiles(tmp_path, transports=("graphql", "grpc")):
    """Two retained checkpoint captures bound to typed provider bindings.

    The gRPC binding is the typed declaration of a future live provider; its
    offline evidence is reconstructed from the same pinned checkpoint payload
    shape because no live gRPC transport is authorized in this slice.
    """
    registry, seed = corpus()
    candidate = candidate_for(registry, seed)
    payload = object_payload(candidate)
    profiles = tuple(profile(index + 1) for index in range(2))
    evidence_store = CampaignEvidenceStore(
        RecoverableStreamJournal(tmp_path / "binding.sqlite"),
        CampaignManifest(
            "a" * 40,
            "b" * 40,
            "c" * 64,
            (("gpr.registry", registry.generation), ("gpr.seed", seed.generation)),
            tuple((p.profile_id, p.generation) for p in profiles),
        ),
        wall_ns=lambda: NOW,
    )
    bindings, evidences = [], []

    async def collect():
        for index, p in enumerate(profiles):
            client = httpx.AsyncClient(
                transport=httpx.MockTransport(
                    lambda req: httpx.Response(
                        200, json=payload, headers={"content-type": "application/json"}
                    )
                ),
                trust_env=False,
            )
            transport = CapturedJsonTransport(
                policy=TransportPolicy(max_attempts=1),
                allowed_hosts={p.hostname},
                client=client,
            )
            gov = ProviderGovernance(
                {p.profile_id: p.entitlement(2000)},
                clock=lambda: 1002,
                wall_clock=lambda: 1002,
            )
            intake = SuiIntakePlane(gov, transport, evidence_store, wall_ns=lambda: NOW)
            ref, raw = await intake.collect(p, checkpoint_request(p.endpoint))
            await client.aclose()
            validate_capture(evidence_store, ref)
            checkpoint = raw["raw_payload"]["data"]["checkpoint"]
            binding = binding_for_profile(p, transports[index])
            bindings.append(binding)
            evidences.append(
                CheckpointConsistencyEvidence(
                    binding_generation=binding.generation,
                    capture_ref=ref,
                    chain_identifier=raw["raw_payload"]["data"]["chainIdentifier"],
                    checkpoint_sequence=checkpoint["sequenceNumber"],
                    checkpoint_digest=checkpoint["digest"],
                    object_id=candidate.pool_id,
                    object_version=checkpoint["query"]["object"]["version"],
                    object_digest=checkpoint["query"]["object"]["digest"],
                    payload_sha256=digest(raw["raw_payload"]),
                    observed_at_ns=raw["observed_at_ns"],
                    available_at_ns=raw["available_at_ns"],
                )
            )

    asyncio.run(collect())
    return bindings, evidences


def test_two_independent_nonsmoke_bindings_verify_offline_and_stay_live_blocked(
    tmp_path,
):
    bindings, evidences = capture_bindings_from_profiles(tmp_path)
    assert {b.transport for b in bindings} == {"graphql", "grpc"}
    assert all(b.smoke_only is False for b in bindings)
    verdict = verify_offline_pair(bindings, evidences)
    assert verdict.status == "OFFLINE_CONSISTENT"
    assert verdict.checkpoint_sequence == 100
    assert verdict.object_id == candidate_for(*corpus()).pool_id
    assert verdict.object_version == 10
    # Byte-identical agreement on the same checkpoint payload is expected:
    # providers are independent by identity; consistency is proven above.
    fixture_payload = object_payload(candidate_for(*corpus()))["data"]
    assert verdict.payload_sha256 == (
        digest({"data": fixture_payload}),
        digest({"data": fixture_payload}),
    )
    live = live_binding_verdict(bindings, evidences)
    assert live.status == "BLOCKED" and live.reason == LIVE_SUI_PROVIDERS_BLOCKED
    assert live.offline.status == "OFFLINE_CONSISTENT"


@pytest.mark.parametrize(
    "failure",
    [
        "checkpoint-digest",
        "object-version",
        "object-digest",
        "genesis",
        "correlated",
        "smoke",
        "transport",
        "credential-url",
        "binding-mismatch",
        "single-binding",
    ],
)
def test_provider_binding_contract_fails_closed(tmp_path, failure):
    bindings, evidences = capture_bindings_from_profiles(tmp_path)
    if failure == "checkpoint-digest":
        drifted = replace(evidences[1], checkpoint_digest="other-digest")
        with pytest.raises(ValueError, match="CHECKPOINT_CONSISTENCY"):
            verify_offline_pair(bindings, (evidences[0], drifted))
        return
    if failure == "object-version":
        drifted = replace(evidences[1], object_version=11)
        with pytest.raises(ValueError, match="OBJECT_VERSION_PROVENANCE"):
            verify_offline_pair(bindings, (evidences[0], drifted))
        return
    if failure == "object-digest":
        drifted = replace(evidences[1], object_digest="other-object-digest")
        with pytest.raises(ValueError, match="OBJECT_VERSION_PROVENANCE"):
            verify_offline_pair(bindings, (evidences[0], drifted))
        return
    if failure == "genesis":
        other = replace(bindings[1], genesis_chain_identifier="other-network")
        drifted = replace(evidences[1], binding_generation=other.generation)
        with pytest.raises(ValueError, match="GENESIS_BINDING"):
            verify_offline_pair((bindings[0], other), (evidences[0], drifted))
        return
    if failure == "correlated":
        twin = replace(bindings[1], operator=bindings[0].operator)
        with pytest.raises(ValueError, match="CORRELATED"):
            verify_offline_pair((bindings[0], twin), evidences)
        return
    if failure == "smoke":
        with pytest.raises(ValueError, match="NONSMOKE"):
            replace(bindings[0], smoke_only=True)
        return
    if failure == "transport":
        with pytest.raises(ValueError, match="TRANSPORT_KIND"):
            replace(bindings[0], transport="jsonrpc")
        return
    if failure == "credential-url":
        with pytest.raises(ValueError, match="CREDENTIAL_FREE"):
            replace(bindings[0], endpoint="https://user:pw@sui.test/state")
        return
    if failure == "binding-mismatch":
        stranger = replace(bindings[1], endpoint="https://sui9.other.test/state")
        with pytest.raises(ValueError, match="EVIDENCE_BINDING"):
            verify_offline_pair((bindings[0], stranger), evidences)
        return
    with pytest.raises(ValueError, match="TWO_INDEPENDENT"):
        verify_offline_pair((bindings[0],), evidences[:1])


def test_provider_evidence_record_time_and_identity_bounds():
    good = CheckpointConsistencyEvidence(
        binding_generation="a" * 64,
        capture_ref="b" * 64,
        chain_identifier="reviewed-fixture-mainnet-id",
        checkpoint_sequence=100,
        checkpoint_digest="cp-digest",
        object_id="0x" + "1" * 64,
        object_version=3,
        object_digest="obj-digest",
        payload_sha256="c" * 64,
        observed_at_ns=10,
        available_at_ns=11,
    )
    assert good.object_id == "0x" + "1" * 64
    with pytest.raises(ValueError, match="TIME_ORDER"):
        replace(good, available_at_ns=9)
    with pytest.raises(ValueError, match="EXACT_SHA256"):
        replace(good, capture_ref="zz")
    with pytest.raises(ValueError, match="CHECKPOINT_SEQUENCE"):
        replace(good, checkpoint_sequence=0)
    with pytest.raises(ValueError, match="EXACT_SHA256"):
        replace(good, payload_sha256="short")


# ---------------------------------------------------------------------------
# Package-bound Move decoder contracts
# ---------------------------------------------------------------------------


def decoder_fixture():
    registry, seed = corpus()
    candidate = candidate_for(registry, seed)
    payload = object_payload(candidate)
    checkpoint = payload["data"]["checkpoint"]
    obj = checkpoint["query"]["object"]
    bcs = base64.b64decode(obj["asMoveObject"]["contents"]["bcs"], validate=True)
    return candidate, checkpoint, obj, bcs


def bcs_with(**overrides):
    fields = {
        "object_version": 10,
        "lot_size": 1,
        "tick_size": 1,
        "taker_fee_numerator": 1,
        "fee_denominator": 1000,
        "bid_depth_units": 100,
        "ask_depth_units": 200,
        **overrides,
    }
    return b"".join(uleb128(fields[name]) for name in POOL_DECODER_LAYOUT)


def obj_with_repr(obj, repr_):
    return {
        **obj,
        "asMoveObject": {
            **obj["asMoveObject"],
            "contents": {
                **obj["asMoveObject"]["contents"],
                "type": {"repr": repr_},
            },
        },
    }


def test_decoder_positive_binds_package_version_decimals_depth_fee():
    _, checkpoint, obj, bcs = decoder_fixture()
    decoded = DeepBookPoolDecoder(expected_package=REVIEWED_PACKAGE).decode(
        checkpoint, obj, bcs
    )
    assert decoded.package_id == REVIEWED_PACKAGE
    assert decoded.object_version == 10 == obj["version"]
    assert decoded.checkpoint == 100
    assert (decoded.lot_size, decoded.tick_size) == (1, 1)
    assert (decoded.taker_fee_numerator, decoded.fee_denominator) == (1, 1000)
    assert (decoded.bid_depth_units, decoded.ask_depth_units) == (100, 200)
    assert decoded.decimals == (6, 6)
    assert decoded.fee_semantics == "FIXTURE_REVIEWED_CONTRACT"
    assert decode_bcs_u64_fields(bcs, POOL_DECODER_LAYOUT)["fee_denominator"] == 1000


@pytest.mark.parametrize(
    "failure",
    [
        "wrong-package",
        "unknown-type",
        "truncated",
        "trailing",
        "noncanonical",
        "u64-overflow",
        "fee-fraction",
        "one-type-arg",
        "noncanonical-repr",
        "metadata-type-mismatch",
        "unknown-fee-label",
    ],
)
def test_decoder_negative_fail_closed(failure):
    candidate, checkpoint, obj, _ = decoder_fixture()
    decoder = DeepBookPoolDecoder(expected_package=REVIEWED_PACKAGE)
    pair = ",".join(candidate.coin_types)
    if failure == "wrong-package":
        other = "0x" + "9" * 64
        with pytest.raises(ValueError, match="PACKAGE_BINDING"):
            DeepBookPoolDecoder(expected_package=other).decode(checkpoint, obj, b"")
        return
    if failure == "unknown-type":
        mutated = obj_with_repr(obj, REVIEWED_PACKAGE + "::vault::Pool<" + pair + ">")
        with pytest.raises(ValueError, match="UNKNOWN_MOVE_TYPE"):
            decoder.decode(checkpoint, mutated, pool_state_bcs())
        return
    if failure == "truncated":
        with pytest.raises(ValueError, match="TRUNCATED"):
            decoder.decode(checkpoint, obj, pool_state_bcs()[:-2])
        return
    if failure == "trailing":
        with pytest.raises(ValueError, match="TRAILING"):
            decoder.decode(checkpoint, obj, pool_state_bcs() + b"\x00")
        return
    if failure == "noncanonical":
        body = bcs_with().replace(uleb128(10), b"\x8a\x00")
        with pytest.raises(ValueError, match="NONCANONICAL"):
            decoder.decode(checkpoint, obj, body)
        return
    if failure == "u64-overflow":
        overflow = (b"\xff" * 9) + b"\x7f"  # > 2**64 - 1
        body = b"".join(
            [
                overflow,
                uleb128(1),
                uleb128(1),
                uleb128(1),
                uleb128(1000),
                uleb128(100),
                uleb128(200),
            ]
        )
        with pytest.raises(ValueError, match="OVERFLOW"):
            decoder.decode(checkpoint, obj, body)
        return
    if failure == "fee-fraction":
        with pytest.raises(ValueError, match="FEE_FRACTION"):
            decoder.decode(checkpoint, obj, bcs_with(taker_fee_numerator=1000))
        return
    if failure == "one-type-arg":
        mutated = obj_with_repr(
            obj, REVIEWED_PACKAGE + "::pool::Pool<" + candidate.coin_types[0] + ">"
        )
        with pytest.raises(ValueError, match="TYPE_ARGUMENTS"):
            decoder.decode(checkpoint, mutated, pool_state_bcs())
        return
    if failure == "noncanonical-repr":
        mutated = obj_with_repr(obj, "0x3::pool::Pool<0x2::sui::SUI,0x2::sui::SUI>")
        with pytest.raises(ValueError, match="CANONICAL_MOVE_TYPE"):
            decoder.decode(checkpoint, mutated, pool_state_bcs())
        return
    if failure == "metadata-type-mismatch":
        drifted = {
            **checkpoint,
            "query": {
                **checkpoint["query"],
                "b": {
                    **checkpoint["query"]["b"],
                    "contents": {
                        **checkpoint["query"]["b"]["contents"],
                        "type": {"repr": "0x2::coin::CoinMetadata<0x2::sui::SUI>"},
                    },
                },
            },
        }
        with pytest.raises(ValueError, match="METADATA_TYPE"):
            decoder.decode(drifted, obj, pool_state_bcs())
        return
    with pytest.raises(ValueError, match="FEE_SEMANTICS"):
        DeepBookPoolDecoder(
            expected_package=REVIEWED_PACKAGE, fee_semantics="DYNAMIC_MAINNET"
        )


def test_pool_type_args_and_metadata_aliases_bind_in_order():
    registry, seed = corpus()
    candidate = candidate_for(registry, seed)
    checkpoint = object_payload(candidate)["data"]["checkpoint"]
    obj = checkpoint["query"]["object"]
    package, module, name, args = parse_move_type(
        obj["asMoveObject"]["contents"]["type"]["repr"]
    )
    assert package == REVIEWED_PACKAGE and (module, name) == ("pool", "Pool")
    assert tuple(args) == tuple(candidate.coin_types)
    decimals = []
    for arg, alias in zip(args, ("a", "b"), strict=True):
        metadata = checkpoint["query"][alias]
        assert metadata["contents"]["type"]["repr"] == (
            "0x2::coin::CoinMetadata<" + arg + ">"
        )
        decimals.append(
            metadata_decimals(
                base64.b64decode(metadata["contents"]["bcs"], validate=True),
                address=metadata["address"],
                tag=metadata["contents"]["type"]["repr"],
                expected_coin_type=arg,
            )
        )
    assert decimals == [6, 6]
    assert metadata_bcs("0x" + "4" * 64, 6)[32] == 6
    assert REVIEWED_FEE_SEMANTICS == {"FIXTURE_REVIEWED_CONTRACT"}
