"""Governed economic read probes, including unsigned 0x reference POST.

No instruction decoding, transaction object, wallet, signer or sender exists.
Provider responses (including unsigned instructions) remain inert raw evidence.
"""

import asyncio
from contextvars import ContextVar
from dataclasses import asdict, dataclass, replace
import time
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from src.provider_governance import (
    AdmissionRequest,
    ProviderOperation,
    ProviderAdmissionError,
)
from src.qualification_campaign.identity import digest
from src.qualification_campaign.evidence import redact_payload
from src.qualification_campaign.profiles import ProviderProfile
from src.qualification_campaign.sources import SourceReadRequest
from src.routing.transport import SanitizedTransportError
from .funnel import QuotePreview, normalize_jupiter, uint

_active_reference_read: ContextVar[dict | None] = ContextVar(
    "gpr02_active_reference_read", default=None
)


@dataclass(frozen=True)
class ReadContract:
    source_id: str
    profile: ProviderProfile
    docs_git_sha: str
    docs_sha256: str
    schema_sha256: str
    method: str = "GET"
    auth_header: str | None = None
    purpose: str = "REFERENCE_ONLY"
    semantic_headers: tuple[tuple[str, str], ...] = (("Accept", "application/json"),)
    request_endpoint: str | None = None

    def __post_init__(self):
        if (
            self.method not in ("GET", "POST")
            or self.purpose != "REFERENCE_ONLY"
            or self.profile.role != "discovery"
            or self.auth_header not in (None, "x-api-key", "0x-api-key")
        ):
            raise ValueError("READ_ONLY_REFERENCE_CONTRACT_REQUIRED")
        if (
            len(self.docs_git_sha) != 40
            or any(c not in "0123456789abcdef" for c in self.docs_git_sha)
            or any(
                len(h) != 64 or any(c not in "0123456789abcdef" for c in h)
                for h in (self.docs_sha256, self.schema_sha256)
            )
        ):
            raise ValueError("EXACT_AUTHORITATIVE_CONTRACT_PINS_REQUIRED")
        if (
            self.method == "POST"
            and self.profile.endpoint != "https://api.0x.org/solana/swap-instructions"
        ):
            raise ValueError("ONLY_DOCUMENTED_UNSIGNED_QUOTE_POST_ALLOWED")
        required = (("Accept", "application/json"),) + (
            (("Content-Type", "application/json"),) if self.method == "POST" else ()
        )
        if tuple(self.semantic_headers) != required:
            raise ValueError("PINNED_READ_ONLY_PROTOCOL_HEADERS_REQUIRED")
        if self.request_endpoint is not None and (
            self.profile.endpoint != "https://mfx-stats-mainnet.fly.dev/tickers"
            or self.request_endpoint != "https://mfx-stats-mainnet.fly.dev/orderbook"
            or self.method != "GET"
        ):
            raise ValueError("ONLY_SHARED_MANIFEST_READ_ENDPOINT_ALLOWED")

    @property
    def generation(self):
        return digest(asdict(self))

    def entitlement(self, *, expires_at_epoch_seconds):
        return replace(
            self.profile.entitlement(expires_at_epoch_seconds=expires_at_epoch_seconds),
            allowed_http_methods=frozenset({self.method}),
            allowed_endpoints=(
                (self.profile.endpoint, self.request_endpoint)
                if self.request_endpoint
                else (self.profile.endpoint,)
            ),
            allowed_query_parameters=(
                frozenset({"depth", "ticker_id"})
                if self.request_endpoint
                else frozenset(self.profile.allowed_query_parameters)
            ),
        )


class GovernedReadPlane:
    def __init__(self, governance, transport, evidence, *, wall_ns=time.time_ns):
        if transport.policy.max_attempts != 1:
            raise ValueError("ONE_CAPTURE_PER_PHYSICAL_ATTEMPT_REQUIRED")
        self.gov, self.transport, self.evidence, self.wall_ns = (
            governance,
            transport,
            evidence,
            wall_ns,
        )
        governance.bind_transport(transport)

    async def collect(self, contract, request, *, credential=None, json_body=None):
        p, started = contract.profile, self.wall_ns()
        generations = dict(self.evidence.manifest.source_generations)
        if (
            generations.get(p.profile_id) != p.generation
            or generations.get(contract.source_id) != contract.generation
        ):
            raise ValueError("REFERENCE_SOURCE_OR_PROVIDER_GENERATION_MISMATCH")
        if (
            request.url != (contract.request_endpoint or p.endpoint)
            or tuple(request.semantic_headers) != tuple(contract.semantic_headers)
            or set(dict(request.params))
            - (
                {"depth", "ticker_id"}
                if contract.request_endpoint
                else set(p.allowed_query_parameters)
            )
            or (contract.method == "GET" and json_body is not None)
        ):
            raise ValueError("REFERENCE_REQUEST_CONTRACT_MISMATCH")
        if contract.method == "POST":
            from src.config.chain_registry import validate_pubkey

            if (
                not isinstance(json_body, dict)
                or set(json_body)
                != {"token_in", "token_out", "amount_in", "taker", "slippage_bps"}
                or not 0 <= json_body["slippage_bps"] <= 50
            ):
                raise ValueError("0X_BOUNDED_REFERENCE_REQUEST_REQUIRED")
            for k in ("token_in", "token_out", "taker"):
                validate_pubkey(json_body[k])
            uint(json_body["amount_in"])
        fingerprint = digest(
            {"request": asdict(request), "method": contract.method, "body": json_body}
        )
        envelope = {
            "kind": "gpr02_reference_read",
            "source_id": contract.source_id,
            "source_generation": contract.generation,
            "provider_id": p.profile_id,
            "provider_generation": p.generation,
            "provider": p.provider,
            "operator": p.operator,
            "correlation_group": p.correlation_group,
            "request": asdict(request),
            "request_body": json_body,
            "request_fingerprint": fingerprint,
            "observed_at_ns": started,
            "http_status": None,
            "raw_payload": None,
            "response_hash": None,
            "physical_attempt": False,
            "logical_attempt_started": False,
            "quality_state": "pending",
            "evidence_state": "DISCOVERY_ONLY",
            "live_authorization": False,
        }
        headers = {
            **dict(request.semantic_headers),
            **(
                {contract.auth_header: credential}
                if contract.auth_header and credential
                else {}
            ),
        }
        try:
            if contract.auth_header and not credential:
                envelope["quality_state"] = "missing-credential-binding"
                envelope["binding_name"] = p.credential_ref
            else:
                self.evidence.claim_attempt(p)
                admission = AdmissionRequest(
                    work_id="gpr02-read:" + uuid4().hex,
                    provider_id=p.profile_id,
                    operation=ProviderOperation.DISCOVERY,
                    request_fingerprint=fingerprint,
                    fairness_key="gpr02-reference",
                    deadline_at=self.gov.clock() + 15,
                    expected_generation=p.generation,
                )

                async def physical():
                    envelope["logical_attempt_started"] = True
                    token = _active_reference_read.set(envelope)
                    try:
                        return await self.transport.request(
                            contract.method,
                            request.url,
                            params=dict(request.params),
                            headers=headers,
                            json_body=json_body,
                        )
                    finally:
                        _active_reference_read.reset(token)

                # Observe the existing canonical issue guard only after it grants.
                # Context-local state keeps concurrent read envelopes independent.
                self.gov.bind_transport(self.transport)
                guard = self.transport.attempt_guard

                async def observe_grant(request, attempt):
                    lease = await guard(request, attempt)
                    active = _active_reference_read.get()
                    if active is not None:
                        active["physical_attempt"] = True
                    return lease

                self.transport.attempt_guard = observe_grant

                status, response_headers, payload = await self.gov.execute_physical(
                    admission,
                    physical,
                    credential_ref=p.credential_ref,
                    credential_generation=p.credential_generation,
                )
                # Existing redactor supports x-api-key; map the 0x credential for reflection removal.
                retained = redact_payload(
                    payload, {"x-api-key": credential} if credential else {}
                )
                envelope.update(
                    physical_attempt=True,  # An actual HTTP response also confirms issue.
                    http_status=status,
                    raw_payload=retained,
                    response_hash=digest(payload),
                    raw_payload_hash=digest(retained),
                    retry_after=response_headers.get("retry-after"),
                    quality_state=(
                        "accepted"
                        if status == 200
                        else (
                            "rate-limited"
                            if status == 429
                            else (
                                "unauthorized" if status in (401, 403) else "http-error"
                            )
                        )
                    ),
                )
        except asyncio.CancelledError:
            envelope["quality_state"] = "cancelled"
            raise
        except (
            ProviderAdmissionError,
            SanitizedTransportError,
            OSError,
            ValueError,
        ) as exc:
            envelope.update(
                quality_state="quota-or-transport-error", error=type(exc).__name__
            )
            if isinstance(exc, SanitizedTransportError):
                envelope["failure_reason"] = str(exc)
            if isinstance(exc, ProviderAdmissionError):
                envelope["error_code"] = exc.code.value
        finally:
            envelope["available_at_ns"] = self.wall_ns()
            ref = self.evidence.append(
                contract.source_id,
                envelope,
                observed_at_ns=started,
                available_at_ns=envelope["available_at_ns"],
            )
        return ref, envelope


def jupiter_request(input_mint, output_mint, amount, *, direct=False, sanctum=False):
    params = {
        "inputMint": input_mint,
        "outputMint": output_mint,
        "amount": str(uint(amount)),
        "slippageBps": "50",
        "swapMode": "ExactIn",
        "restrictIntermediateTokens": "true",
        "instructionVersion": "V2",
    }
    if direct:
        params["onlyDirectRoutes"] = "true"
    if sanctum:
        params["dexes"] = "Sanctum,Sanctum Infinity"
    return SourceReadRequest(
        "https://api.jup.ag/swap/v1/quote",
        tuple(sorted(params.items())),
        (("Accept", "application/json"),),
    )


def normalize_zero_x(payload, *, body, observed_at_ns, contract, raw_evidence_ref):
    routes = payload.get("route_plan")
    if not isinstance(routes, list) or not 1 <= len(routes) <= 16:
        raise ValueError("BOUNDED_0X_ROUTE_REQUIRED")
    mints = tuple(sorted({m for r in routes for m in (r["token_in"], r["token_out"])}))
    if not {body["token_in"], body["token_out"]} <= set(mints):
        raise ValueError("0X_ROUTE_ENDPOINTS_MISMATCH")
    # The authoritative schema gives no context slot: do not invent one.
    return QuotePreview(
        body["token_in"],
        body["token_out"],
        uint(body["amount_in"]),
        uint(payload["amount_out"]),
        uint(payload["min_amount_out"]),
        None,
        observed_at_ns,
        contract.source_id,
        contract.profile.generation,
        contract.profile.correlation_group,
        raw_evidence_ref,
        mints,
        all(
            {r["token_in"], r["token_out"]} == {body["token_in"], body["token_out"]}
            for r in routes
        ),
    )


def normalized_reference(evidence, contract, request, ref, envelope, *, body=None):
    if (
        envelope["quality_state"] != "accepted"
        or envelope.get("physical_attempt") is not True
        or envelope.get("http_status") != 200
    ):
        return None

    try:
        if contract.source_id == "gpr02-0x-preview":
            quote = normalize_zero_x(
                envelope["raw_payload"],
                body=body,
                observed_at_ns=envelope["observed_at_ns"],
                contract=contract,
                raw_evidence_ref=ref,
            )
        else:
            quote = normalize_jupiter(
                envelope["raw_payload"],
                request=request,
                observed_at_ns=envelope["observed_at_ns"],
                source_id=contract.source_id,
                provider_generation=contract.profile.generation,
                correlation_group=contract.profile.correlation_group,
                raw_evidence_ref=ref,
            )
        evidence.append(
            "gpr02-quote",
            {
                "kind": "gpr02_quote_preview",
                "quote": asdict(quote),
                "quote_hash": digest(asdict(quote)),
            },
            observed_at_ns=evidence.wall_ns(),
        )
        return quote
    except (ValueError, KeyError, TypeError, AttributeError):
        evidence.append(
            "gpr02-quote",
            {
                "kind": "gpr02_quote_rejected",
                "raw_evidence_ref": ref,
                "reason": "QUOTE_SCHEMA_OR_IDENTITY_REJECTED",
            },
            observed_at_ns=evidence.wall_ns(),
        )
        return None


def normalize_manifest_book(payload, *, market_id, depth=20):
    if payload.get("ticker_id") != market_id or depth != 20:
        raise ValueError("MANIFEST_BOOK_IDENTITY_OR_DEPTH_MISMATCH")
    result = {
        "market_id": market_id,
        "source_time": payload.get("timestamp"),
        "evidence_state": "DISCOVERY_ONLY",
        "exact_graph_allowed": False,
    }
    for side in ("bids", "asks"):
        levels = payload.get(side)
        if not isinstance(levels, list) or len(levels) > depth // 2:
            raise ValueError("BOUNDED_MANIFEST_BOOK_REQUIRED")
        parsed = []
        for level in levels:
            if not isinstance(level, list) or len(level) != 2:
                raise ValueError("MANIFEST_BOOK_LEVEL_SCHEMA_MISMATCH")
            try:
                values = tuple(Decimal(str(v)) for v in level)
            except (InvalidOperation, ValueError):
                raise ValueError("MANIFEST_BOOK_NUMERIC_SCHEMA_MISMATCH") from None
            if any(not v.is_finite() or v <= 0 or len(str(v)) > 64 for v in values):
                raise ValueError("MANIFEST_BOOK_POSITIVE_BOUNDED_LEVEL_REQUIRED")
            parsed.append(tuple(str(v) for v in values))
        result[side] = tuple(parsed)
    result["depth_verified"] = False
    result["fee_verified"] = False
    return result
