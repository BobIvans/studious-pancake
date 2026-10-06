"""Existing provider governance/evidence owners with separate Sui normalization."""

import asyncio
import base64
import hashlib
import json
import time
from contextlib import asynccontextmanager
from dataclasses import asdict, replace
from uuid import uuid4

import httpx

from src.provider_governance import (
    AdmissionRequest,
    ProviderOperation,
    ProviderAdmissionError,
)
from src.qualification_campaign.identity import digest
from src.qualification_campaign.evidence import redact_payload
from src.routing.transport import (
    HttpxJsonTransport,
    TransportPolicy,
    build_tls_context,
    SanitizedTransportError,
)
from src.research_economic_graph.graph import retained_records, require_generation
from src.research_economic_graph import (
    ResearchEvidence,
    ResearchRelation,
    EvidenceState,
    ExecutionClass,
    Heat,
)
from .models import SuiCandidate
from .sources import StructuralRate, PoolIndexAdapter, ScallopRateAdapter


class CapturedJsonTransport(HttpxJsonTransport):
    """Retain bounded negative bodies before the canonical JSON parser rejects them."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.raw_capture = None
        # The entire transaction is serialized across planes sharing this
        # transport so parsed payloads and retained bytes never cross requests.
        self.capture_lock = asyncio.Lock()

    async def _read_bounded(self, response):
        self.raw_capture = {
            **(self.raw_capture or {}),
            "http_status": response.status_code,
            "content_type": response.headers.get("content-type"),
            "declared_content_length": response.headers.get("content-length"),
            "response_limit_bytes": self.policy.max_response_bytes,
            "json_node_limit": self.policy.max_json_nodes,
            "body_capture_complete": False,
        }
        body = await super()._read_bounded(response)
        self.raw_capture = {
            **self.raw_capture,
            "http_status": response.status_code,
            "content_type": response.headers.get("content-type"),
            "wire_payload_sha256": hashlib.sha256(body).hexdigest(),
            "wire_payload_base64": base64.b64encode(body).decode(),
            "wire_payload_bytes": len(body),
            "body_capture_complete": True,
        }
        return body

    async def _physical_attempt(self, request, attempt):
        self.raw_capture = {
            "sent_content_length": request.headers.get("content-length"),
            "sent_content_type": request.headers.get("content-type"),
            "sent_accept": request.headers.get("accept"),
            "request_wire_sha256": hashlib.sha256(request.content).hexdigest(),
            "request_wire_bytes": len(request.content),
            "request_wire_base64": base64.b64encode(request.content).decode(),
        }
        return await super()._physical_attempt(request, attempt)


@asynccontextmanager
async def sui_transport(hosts, environment):
    # Use the existing supported CA/TLS construction and explicit platform proxy.
    policy = TransportPolicy(
        max_attempts=1, ca_bundle_path=environment.get("SSL_CERT_FILE")
    )
    context, _ = build_tls_context(policy)
    async with httpx.AsyncClient(
        proxy=environment.get("HTTPS_PROXY"),
        verify=context,
        trust_env=False,
        follow_redirects=False,
        timeout=httpx.Timeout(15, connect=10),
    ) as client:
        async with CapturedJsonTransport(
            policy=policy, allowed_hosts=frozenset(hosts), client=client
        ) as transport:
            yield transport


class SuiIntakePlane:
    def __init__(self, governance, transport, evidence, *, wall_ns=time.time_ns):
        if transport.policy.max_attempts != 1:
            raise ValueError("SUI_ONE_ENVELOPE_PER_PHYSICAL_ATTEMPT_REQUIRED")
        self.governance, self.transport, self.evidence, self.wall_ns = (
            governance,
            transport,
            evidence,
            wall_ns,
        )
        governance.bind_transport(transport)

    async def collect(self, profile, request, adapter=None):
        async with self.transport.capture_lock:
            original = self.transport.policy
            self.transport.policy = replace(
                original,
                max_response_bytes=profile.max_response_bytes,
                max_wire_bytes=profile.max_response_bytes,
                max_json_nodes=profile.max_json_nodes,
            )
            try:
                return await self._collect(profile, request, adapter)
            finally:
                self.transport.policy = original

    async def _collect(self, profile, request, adapter=None):
        if (
            dict(self.evidence.manifest.source_generations).get(profile.profile_id)
            != profile.generation
        ):
            raise ValueError("SUI_PROFILE_GENERATION_MISMATCH")
        if (
            request.url != profile.endpoint
            or request.method != profile.method
            or (
                request.purpose != profile.purpose
                and not (
                    profile.purpose == "checkpoint"
                    and request.purpose == "checkpoint-object"
                )
            )
            or set(dict(request.params)) - set(profile.allowed_query_parameters)
        ):
            raise ValueError("SUI_REQUEST_OUTSIDE_REVIEWED_PROFILE")
        # This slice supports anonymous reads. A secret-bearing transport must
        # redact raw response bytes before retention; never resolve secrets here.
        if profile.credential_ref != "anonymous-public-read":
            raise ValueError("SUI_CREDENTIAL_BINDING_NOT_CONFIGURED")
        started = self.wall_ns()
        envelope = {
            "kind": "gpr03_sui_raw",
            "profile": asdict(profile),
            "source_generation": profile.generation,
            "request": asdict(request),
            "request_hash": request.fingerprint,
            "response_hash": None,
            "observed_at_ns": started,
            "quality": "pending",
            "raw_payload": None,
            "classification": "DISCOVERY_ONLY",
            "physical_attempt_started": False,
            "exact_state_ready": False,
        }
        if (
            (
                profile.source_kind in ("deepbook", "aftermath", "cetus")
                and (
                    not isinstance(adapter, PoolIndexAdapter)
                    or adapter.venue != profile.source_kind
                )
            )
            or (
                profile.source_kind == "scallop"
                and not isinstance(adapter, ScallopRateAdapter)
            )
            or (
                profile.source_kind in ("graphql", "deepbook-book")
                and adapter is not None
            )
        ):
            raise ValueError("SUI_SOURCE_ADAPTER_GENERATION_MISMATCH")
        candidates: tuple[SuiCandidate, ...] = ()
        rates: tuple[StructuralRate, ...] = ()
        self.transport.raw_capture = None
        try:
            self.evidence.claim_attempt(profile)
            admission = AdmissionRequest(
                "sui-read:" + uuid4().hex,
                profile.profile_id,
                ProviderOperation.BACKFILL,
                request.fingerprint,
                "gpr03-shadow",
                self.governance.clock() + 20,
                expected_generation=profile.generation,
            )

            async def physical():
                envelope["physical_attempt_started"] = True
                headers = dict(request.semantic_headers)
                if request.serialized_body is not None:
                    headers["Content-Length"] = str(len(request.serialized_body))
                return await self.transport.request(
                    request.method,
                    request.url,
                    params=dict(request.params),
                    json_body=request.body,
                    headers=headers,
                )

            status, headers, payload = await self.governance.execute_physical(
                admission,
                physical,
                credential_ref=profile.credential_ref,
                credential_generation=profile.credential_generation,
            )
            envelope.update(
                http_status=status,
                raw_payload=redact_payload(payload, {}),
                response_hash=digest(payload),
                retry_after=headers.get("retry-after"),
            )
            if status != 200:
                envelope["quality"] = "rate-limited" if status == 429 else "http-error"
            elif isinstance(payload, dict) and payload.get("errors"):
                envelope["quality"] = "graphql-errors"
            elif adapter is not None:
                candidates, rates, rejects = adapter.normalize(payload)
                if len(candidates) > 512 or len(rates) > 384:
                    raise ValueError("SUI_BOUNDED_NORMALIZATION_REQUIRED")
                envelope.update(
                    rejections=rejects,
                    quality="accepted" if candidates or rates else "empty-or-rejected",
                )
            else:
                envelope["quality"] = "accepted-read-only"
        except asyncio.CancelledError:
            envelope["quality"] = "cancelled"
            raise
        except (
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            ProviderAdmissionError,
            SanitizedTransportError,
            OSError,
        ) as exc:
            envelope.update(
                quality="schema-or-admission-error", error=type(exc).__name__
            )
            if isinstance(exc, SanitizedTransportError):
                envelope.update(
                    quality="transport-error",
                    failure_reason=str(exc),
                    http_status=exc.status_code,
                )
            if isinstance(exc, ProviderAdmissionError):
                envelope.update(
                    quality="quota-or-admission-denied", error_code=exc.code.value
                )
        finally:
            envelope.update(self.transport.raw_capture or {})
            envelope["available_at_ns"] = max(started, self.wall_ns())
            envelope["raw_payload_hash"] = digest(envelope["raw_payload"])
            ref = self.evidence.append(
                profile.profile_id,
                envelope,
                observed_at_ns=started,
                available_at_ns=envelope["available_at_ns"],
            )
        for candidate in candidates:
            self.evidence.append(
                "gpr03-candidate",
                {
                    "kind": "gpr03_sui_candidate",
                    "candidate": asdict(candidate),
                    "candidate_id": candidate.identity,
                    "raw_ref": ref,
                },
                observed_at_ns=envelope["available_at_ns"],
            )
        for rate in rates:
            self.evidence.append(
                "gpr03-rate",
                {"kind": "gpr03_structural_rate", "rate": asdict(rate), "raw_ref": ref},
                observed_at_ns=envelope["available_at_ns"],
            )
        return ref, envelope


def validate_capture(evidence, ref):
    raw = retained_records(evidence).get(ref)
    if raw is None or raw.get("kind") != "gpr03_sui_raw":
        raise ValueError("SUI_RETAINED_CAPTURE_REQUIRED")
    profile = raw["profile"]
    if digest(profile) != raw["source_generation"] or digest(profile) != dict(
        evidence.manifest.source_generations
    ).get(profile["profile_id"]):
        raise ValueError("SUI_CAPTURE_PROFILE_GENERATION_MISMATCH")
    if (
        digest(raw["request"]) != raw["request_hash"]
        or digest(raw["raw_payload"]) != raw["raw_payload_hash"]
    ):
        raise ValueError("SUI_CAPTURE_REQUEST_OR_PAYLOAD_HASH_MISMATCH")
    if "request_wire_base64" in raw:
        sent = base64.b64decode(raw["request_wire_base64"], validate=True)
        if (
            hashlib.sha256(sent).hexdigest() != raw["request_wire_sha256"]
            or len(sent) != raw["request_wire_bytes"]
        ):
            raise ValueError("SUI_REQUEST_WIRE_HASH_MISMATCH")
        if raw["request"]["body"] is not None:
            if digest(json.loads(sent)) != digest(raw["request"]["body"]) or raw[
                "sent_content_length"
            ] != str(len(sent)):
                raise ValueError("SUI_EXPLICIT_POST_BODY_LENGTH_OR_CONTENT_MISMATCH")
        elif sent:
            raise ValueError("SUI_GET_REQUEST_BODY_FORBIDDEN")
    if raw["response_hash"] is not None and "wire_payload_base64" not in raw:
        raise ValueError("SUI_POSITIVE_WIRE_CAPTURE_REQUIRED")
    if "wire_payload_base64" in raw:
        body = base64.b64decode(raw["wire_payload_base64"], validate=True)
        if (
            hashlib.sha256(body).hexdigest() != raw["wire_payload_sha256"]
            or len(body) != raw["wire_payload_bytes"]
        ):
            raise ValueError("SUI_WIRE_PAYLOAD_HASH_MISMATCH")
        if raw["response_hash"] is not None and (
            digest(json.loads(body)) != raw["response_hash"]
            or raw["response_hash"] != raw["raw_payload_hash"]
        ):
            raise ValueError("SUI_WIRE_PARSED_PAYLOAD_MISMATCH")
    return raw


def ingest_research(graph, evidence):
    require_generation(evidence, graph.registry, graph.seed)
    for raw in retained_records(evidence).values():
        if raw.get("kind") == "gpr03_structural_rate":
            capture = validate_capture(evidence, raw["raw_ref"])
            if (
                capture["profile"]["source_kind"] != "scallop"
                or capture["quality"] != "accepted"
            ):
                raise ValueError("SUI_STRUCTURAL_SOURCE_PROVENANCE_MISMATCH")
            rate = StructuralRate(**raw["rate"])
            _, normalized_rates, _ = ScallopRateAdapter().normalize(
                capture["raw_payload"]
            )
            if rate not in normalized_rates:
                raise ValueError("SUI_RATE_NOT_IN_RETAINED_RAW_CAPTURE")
            try:
                asset = graph.registry.by_identifier("sui-mainnet", rate.coin_type)
            except ValueError:
                continue
            p = capture["profile"]
            observation = ResearchEvidence(
                raw["raw_ref"],
                p["profile_id"],
                capture["source_generation"],
                p["profile_id"],
                capture["source_generation"],
                p["provider"],
                p["operator"],
                p["correlation_group"],
                capture["request_hash"],
                capture["response_hash"],
                capture["raw_payload_hash"],
                capture["observed_at_ns"],
                capture["available_at_ns"],
                capture["quality"],
                source_time=rate.source_time,
            )
            graph.add(
                ResearchRelation(
                    "gpr03-rate:" + digest(asdict(rate)),
                    "STRUCTURAL_RATE_REFERENCE",
                    (asset.asset_id,),
                    Heat.WARM,
                    ExecutionClass.LOCAL_SIGNAL,
                    EvidenceState.DISCOVERY_ONLY,
                    provenance_refs=(raw["raw_ref"],),
                    evidence=(observation,),
                    observed_at_ns=observation.observed_at_ns,
                    quality="source-rate-reference-units-not-yet-qualified",
                    reference=rate.rate_kind,
                )
            )
            continue
        if raw.get("kind") != "gpr03_sui_candidate":
            continue
        capture = validate_capture(evidence, raw["raw_ref"])
        candidate = SuiCandidate(**raw["candidate"])
        if (
            candidate.identity != raw["candidate_id"]
            or capture["quality"] != "accepted"
            or candidate.venue != capture["profile"]["source_kind"]
        ):
            raise ValueError("SUI_CANDIDATE_CAPTURE_PROVENANCE_MISMATCH")
        # Re-normalize retained bytes: rehashing a fabricated candidate grants nothing.
        from .sources import PoolIndexAdapter

        normalized, _, _ = PoolIndexAdapter(candidate.venue).normalize(
            capture["raw_payload"]
        )
        if candidate not in normalized:
            raise ValueError("SUI_CANDIDATE_NOT_IN_RAW_CAPTURE")
        try:
            refs = tuple(
                graph.registry.by_identifier("sui-mainnet", t).asset_id
                for t in candidate.coin_types
            )
        except ValueError:
            # Retain the rejected normalized candidate as the negative evidence;
            # replay does not append new observations or mutate the journal.
            continue
        matching = [
            r for r in graph.seed.relations if set(refs) <= set(r.representations)
        ]
        heat = min(
            (r.heat for r in matching),
            key=lambda h: {Heat.HOT: 0, Heat.EVENT: 1, Heat.WARM: 2, Heat.COLD: 3}[h],
            default=Heat.COLD,
        )
        p = capture["profile"]
        observation = ResearchEvidence(
            raw["raw_ref"],
            p["profile_id"],
            capture["source_generation"],
            p["profile_id"],
            capture["source_generation"],
            p["provider"],
            p["operator"],
            p["correlation_group"],
            capture["request_hash"],
            capture["response_hash"],
            capture["raw_payload_hash"],
            capture["observed_at_ns"],
            capture["available_at_ns"],
            capture["quality"],
        )
        graph.add(
            ResearchRelation(
                "gpr03:" + candidate.identity,
                "SWAP_CANDIDATE",
                refs,
                heat,
                ExecutionClass.LOCAL_SIGNAL,
                EvidenceState.DISCOVERY_ONLY,
                direct_venues=(candidate.venue,),
                known_pool_or_book_ids=(candidate.pool_id,),
                provenance_refs=(raw["raw_ref"],),
                evidence=(observation,),
                observed_at_ns=observation.observed_at_ns,
                quality="sui-indexed-shadow-only",
            )
        )
    return graph
