"""Generic discovery-only source intake consuming the existing source catalog."""

import asyncio
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import re
import time
from typing import Protocol
from urllib.parse import urlsplit
from uuid import uuid4

from src.market.discovery import DiscoveryRequest, _rows, _market
from src.market.source_catalog import MarketDataSource, SourceAccess, SourceFamily
from src.provider_governance import (
    AdmissionRequest,
    ProviderOperation,
    ProviderAdmissionError,
)
from src.routing.transport import SanitizedTransportError
from .identity import digest
from .profiles import ProviderProfile
from .evidence import redact_payload


def _https(value):
    u = urlsplit(value)
    if (
        u.scheme != "https"
        or not u.hostname
        or u.username
        or u.password
        or u.query
        or u.fragment
    ):
        raise ValueError("credential-free official HTTPS URL required")


@dataclass(frozen=True)
class SourceDossier:
    source_id: str
    label: str
    profile: ProviderProfile
    checked_at: str
    docs_sha256: str
    request_schema_version: str
    response_schema_version: str
    schema_fingerprint: str
    terms_url: str
    license_class: str = "UNREVIEWED_PUBLIC_RESEARCH"
    capabilities: tuple[str, ...] = ("candidate-discovery",)
    classification: str = "DISCOVERY_ONLY"
    renewal_ttl_seconds: int = 86400
    slot_id: str | None = None
    daily_quota: int | None = None
    monthly_quota: int | None = None
    commercial_use: str = "UNKNOWN"
    redistribution_allowed: str = "UNKNOWN"
    attribution: str = "UNREVIEWED"
    token_semantics: str = "UNKNOWN"
    oracle_semantics: str = "UNKNOWN"
    schema_version: str = "prequal.source-dossier.v1"

    def __post_init__(self):
        if not all(
            isinstance(v, str) and v.strip()
            for v in (
                self.source_id,
                self.label,
                self.request_schema_version,
                self.response_schema_version,
                self.license_class,
            )
        ):
            raise ValueError("source/schema/license identity required")
        if (
            self.schema_version != "prequal.source-dossier.v1"
            or self.classification != "DISCOVERY_ONLY"
            or self.profile.role != "discovery"
        ):
            raise ValueError(
                "source intake only admits DISCOVERY_ONLY; verified state belongs to RPC verifier"
            )
        for sha in (self.docs_sha256, self.schema_fingerprint):
            if not re.fullmatch("[0-9a-f]{64}", sha):
                raise ValueError("exact docs/schema pin required")
        checked = datetime.fromisoformat(self.checked_at)
        if checked.tzinfo is None:
            raise ValueError("UTC-aware docs review time required")
        _https(self.terms_url)
        if (
            type(self.renewal_ttl_seconds) is not int
            or not 1 <= self.renewal_ttl_seconds <= 604800
        ):
            raise ValueError("bounded docs renewal TTL required")
        if self.slot_id is not None:
            if not re.fullmatch(
                "FREE-SOURCE-0(?:0[1-9]|[1-5][0-9]|6[0-4])", self.slot_id
            ):
                raise ValueError(
                    "intake slot must be one of existing FREE-SOURCE-001..064"
                )
        if set(self.capabilities) != {"candidate-discovery"}:
            raise ValueError("discovery source cannot grant exact execution capability")
        object.__setattr__(self, "capabilities", tuple(self.capabilities))
        for limit in (self.daily_quota, self.monthly_quota):
            if limit is not None and (type(limit) is not int or limit <= 0):
                raise ValueError("positive or explicitly UNKNOWN quota required")
        # A declared period cap must be at least as conservative as the permanent campaign cap.
        if any(
            limit is not None and self.profile.campaign_attempt_cap > limit
            for limit in (self.daily_quota, self.monthly_quota)
        ):
            raise ValueError("campaign cap exceeds declared period quota")

    @property
    def generation(self):
        return digest(asdict(self))

    def require_current(self, now_ns):
        age = now_ns / 10**9 - datetime.fromisoformat(self.checked_at).timestamp()
        if not 0 <= age <= self.renewal_ttl_seconds:
            raise ValueError("SOURCE_DOCS_STALE_OR_FUTURE")

    def catalog_entry(self):
        return MarketDataSource(
            self.source_id,
            self.label,
            SourceFamily.DISCOVERY,
            ("solana-mainnet",),
            SourceAccess.PUBLIC_LIMITED,
            (self.profile.official_docs,),
            "Discovery candidates only; on-chain identity/state verification required. Unknown costs/token/oracle/license semantics cannot qualify.",
        )


@dataclass(frozen=True)
class Candidate:
    market_id: str
    mints: tuple[str, str]
    venue_label: str
    chain: str = "solana-mainnet"

    def __post_init__(self):
        from src.config.chain_registry import validate_pubkey

        validate_pubkey(self.market_id)
        if (
            len(self.mints) != 2
            or self.mints[0] == self.mints[1]
            or self.chain != "solana-mainnet"
            or not self.venue_label
        ):
            raise ValueError("complete Solana candidate identity required")
        for mint in self.mints:
            validate_pubkey(mint)
        object.__setattr__(self, "mints", tuple(sorted(self.mints)))

    @property
    def identity(self):
        # Venue label is untrusted indexed metadata, not a second pool identity.
        return digest(
            {"chain": self.chain, "market_id": self.market_id, "mints": self.mints}
        )


@dataclass(frozen=True)
class SourceReadRequest:
    url: str
    params: tuple[tuple[str, str], ...] = ()
    semantic_headers: tuple[tuple[str, str], ...] = ()

    def __post_init__(self):
        _https(self.url)
        if any(
            k.lower() not in ("accept", "content-type", "user-agent") or len(v) > 512
            for k, v in self.semantic_headers
        ):
            raise ValueError(
                "credentials must use profile binding, never recorded request headers"
            )
        if any(len(k) > 128 or len(v) > 1024 for k, v in self.params):
            raise ValueError("bounded source query required")

    @property
    def fingerprint(self):
        return digest(asdict(self))


class DiscoveryAdapter(Protocol):
    def request(self) -> SourceReadRequest: ...
    def normalize(
        self, payload: object
    ) -> tuple[tuple[Candidate, ...], dict[str, int]]: ...


class CatalogDiscoveryAdapter:
    """Reuses existing typed request builders and canonical source decoders."""

    def __init__(self, request: DiscoveryRequest):
        self.typed_request = request

    def request(self):
        url, params = self.typed_request.endpoint()
        headers = (
            (("Accept", "application/json;version=20230302"),)
            if self.typed_request.source_id == "geckoterminal"
            else ()
        )
        return SourceReadRequest(url, tuple(sorted(params.items())), headers)

    def schema_contract(self):
        return {
            "owner": "src.market.discovery",
            "source_id": self.typed_request.source_id,
            "request": "DiscoveryRequest.v1",
            "response": "DiscoveredMarket.v1",
            "classification": "DISCOVERY_ONLY",
        }

    def context(self, payload):
        if isinstance(payload, dict):
            return {
                "source_provided_time": payload.get("updated_at")
                or payload.get("timestamp")
            }
        return {}

    def normalize(self, payload):
        request = self.typed_request
        candidates = []
        rejections = Counter()
        for row in _rows(request.source_id, payload):
            try:
                if (
                    request.required_program_id is not None
                    and row.get("programId") != request.required_program_id
                ):
                    rejections["program-filter"] += 1
                    continue
                m = _market(request.source_id, row, "normalization-only")
                candidates.append(Candidate(m.market_id, m.mints, m.venue_label))
            except (ValueError, KeyError, TypeError, AttributeError):
                rejections["candidate-schema-rejected"] += 1
        return tuple(candidates), dict(rejections)


def deduplicate_candidates(records):
    normalized = {}
    for candidate, provenance in records:
        row = normalized.setdefault(
            candidate.identity,
            {
                "candidate": asdict(candidate),
                "classification": "DISCOVERY_ONLY",
                "exact_state_ready": False,
                "provenance": [],
                "venue_labels": [],
            },
        )
        if provenance not in row["provenance"]:
            row["provenance"].append(provenance)
        if candidate.venue_label not in row["venue_labels"]:
            row["venue_labels"].append(candidate.venue_label)
    for row in normalized.values():
        row["provenance"].sort(key=digest)
        row["venue_labels"].sort()
        row["candidate"]["venue_label"] = row["venue_labels"][0]
    return {k: normalized[k] for k in sorted(normalized)}


class SourceIntakePlane:
    def __init__(
        self,
        catalog,
        governance,
        transport,
        evidence,
        *,
        wall_ns=time.time_ns,
        credential_headers=None,
    ):
        if transport.policy.max_attempts != 1:
            raise ValueError("physical observation capture requires max_attempts=1")
        self.catalog = catalog
        self.governance = governance
        self.transport = transport
        self.evidence = evidence
        self.wall_ns = wall_ns
        self.credential_headers = credential_headers or {}
        governance.bind_transport(transport)

    async def collect(self, dossier: SourceDossier, adapter: DiscoveryAdapter):
        self.catalog.require(dossier.source_id)
        profile = dossier.profile
        dossier.require_current(self.wall_ns())
        if (
            dict(self.evidence.manifest.source_generations).get(dossier.source_id)
            != dossier.generation
        ):
            raise ValueError("SOURCE_DOSSIER_GENERATION_MISMATCH")
        # Both the dossier and profile are pinned, because quotas/credentials are executable policy.
        if (
            dict(self.evidence.manifest.source_generations).get(profile.profile_id)
            != profile.generation
        ):
            raise ValueError("PROVIDER_GENERATION_MISMATCH")
        if digest(adapter.schema_contract()) != dossier.schema_fingerprint:
            raise ValueError("SOURCE_SCHEMA_CONTRACT_MISMATCH")
        request = adapter.request()
        if request.url != profile.endpoint or set(dict(request.params)) - set(
            profile.allowed_query_parameters
        ):
            raise ValueError("SOURCE_REQUEST_PROFILE_MISMATCH")
        started = self.wall_ns()
        envelope = {
            "kind": "source_observation",
            "source_id": dossier.source_id,
            "source_generation": dossier.generation,
            "provider_id": profile.profile_id,
            "provider": profile.provider,
            "operator": profile.operator,
            "correlation_group": profile.correlation_group,
            "provider_generation": profile.generation,
            "request_fingerprint": request.fingerprint,
            "request": asdict(request),
            "response_hash": None,
            "schema_fingerprint": dossier.schema_fingerprint,
            "request_schema_version": dossier.request_schema_version,
            "response_schema_version": dossier.response_schema_version,
            "observed_at_ns": started,
            "source_provided_time": None,
            "slot": None,
            "root": None,
            "finality": None,
            "classification": "DISCOVERY_ONLY",
            "quality_state": "pending",
            "raw_payload": None,
        }
        candidates = ()
        rejections = {}
        try:
            self.evidence.claim_attempt(profile)
            entitlement = self.governance.entitlement(profile.profile_id)
            if entitlement.generation != profile.generation:
                raise ValueError("ENTITLEMENT_GENERATION_MISMATCH")
            headers = {
                **dict(request.semantic_headers),
                **self.credential_headers.get(profile.profile_id, {}),
            }
            admission = AdmissionRequest(
                work_id="source:" + uuid4().hex,
                provider_id=profile.profile_id,
                operation=ProviderOperation.DISCOVERY,
                request_fingerprint=request.fingerprint,
                fairness_key="campaign-discovery",
                deadline_at=self.governance.clock() + 15,
                expected_generation=profile.generation,
            )
            status, response_headers, payload = await self.governance.execute_physical(
                admission,
                lambda: self.transport.request(
                    "GET", request.url, params=dict(request.params), headers=headers
                ),
                credential_ref=profile.credential_ref,
                credential_generation=profile.credential_generation,
            )
            envelope.update(
                http_status=status,
                response_hash=digest(payload),
                raw_payload=redact_payload(payload, headers),
                retry_after=response_headers.get("retry-after"),
                hash_kind="canonical-json-sha256",
            )
            if status == 200:
                candidates, rejections = adapter.normalize(payload)
                if len(candidates) > 512 or any(
                    not isinstance(c, Candidate) for c in candidates
                ):
                    raise ValueError("bounded normalized candidates required")
                context = (
                    adapter.context(payload) if hasattr(adapter, "context") else {}
                )
                if set(context) - {
                    "source_provided_time",
                    "slot",
                    "root",
                    "finality",
                    "sequence",
                }:
                    raise ValueError("unsupported source context")
                envelope.update(context)
                envelope["raw_payload_hash"] = digest(envelope["raw_payload"])
                envelope["redaction_applied"] = (
                    envelope["raw_payload_hash"] != envelope["response_hash"]
                )
                envelope["quality_state"] = (
                    "accepted" if candidates else "empty-response"
                )
                if rejections:
                    envelope["quality_state"] = (
                        "accepted-with-rejections" if candidates else "schema-drift"
                    )
                envelope["rejections"] = rejections
            else:
                envelope["quality_state"] = (
                    "rate-limited"
                    if status == 429
                    else "unauthorized" if status in (401, 403) else "http-error"
                )
        except asyncio.CancelledError:
            envelope["quality_state"] = "cancelled"
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
                error=type(exc).__name__, quality_state="schema-or-admission-error"
            )
            if isinstance(exc, ProviderAdmissionError):
                envelope["quality_state"] = "quota-or-admission-denied"
                envelope["error_code"] = exc.code.value
            if isinstance(exc, SanitizedTransportError):
                envelope["failure_reason"] = str(exc)
                envelope["quality_state"] = (
                    "timeout" if "timed out" in str(exc) else "transport-error"
                )
        finally:
            if envelope.get("http_status") is not None:
                envelope["raw_payload_hash"] = digest(envelope["raw_payload"])
                envelope["redaction_applied"] = (
                    envelope["raw_payload_hash"] != envelope["response_hash"]
                )
            envelope["available_at_ns"] = self.wall_ns()
            observation_id = self.evidence.append(
                dossier.source_id,
                envelope,
                observed_at_ns=started,
                available_at_ns=envelope["available_at_ns"],
            )
        records = []
        for candidate in candidates:
            provenance = {
                "source_id": dossier.source_id,
                "source_generation": dossier.generation,
                "raw_evidence_id": observation_id,
                "request_fingerprint": request.fingerprint,
                "response_hash": envelope["response_hash"],
            }
            self.evidence.append(
                "candidate",
                {
                    "kind": "discovery_candidate",
                    "candidate": asdict(candidate),
                    "candidate_id": candidate.identity,
                    "provenance": provenance,
                    "classification": "DISCOVERY_ONLY",
                },
                observed_at_ns=envelope["available_at_ns"],
            )
            records.append((candidate, provenance))
        return tuple(records), envelope

    def link_verification(
        self, candidate: Candidate, provenance: dict, verification_id: str
    ):
        events = self.evidence.journal.events(available_at_ns=2**63 - 1)
        by_id = {e.identity: e for e in events}
        if (
            provenance.get("raw_evidence_id") not in by_id
            or verification_id not in by_id
        ):
            raise ValueError(
                "verification provenance must reference retained campaign evidence"
            )
        retained_candidates = [
            self.evidence.expand(e.payload_json)
            for e in events
            if e.source == "candidate"
        ]
        if not any(
            c.get("candidate_id") == candidate.identity
            and c.get("provenance") == provenance
            for c in retained_candidates
        ):
            raise ValueError("candidate provenance is not retained")
        body = self.evidence.expand(by_id[verification_id].payload_json)
        if body.get("kind") != "rooted_snapshot_bundle":
            raise ValueError("verification must be on-chain quorum evidence")
        from .rpc import validate_quorum_evidence

        validate_quorum_evidence(body, self.evidence)
        captures = [
            self.evidence.expand(by_id[r].payload_json)["payload"]
            for r in body.get("capture_refs", [])
            if r in by_id
        ]
        from src.providers.raydium_cpmm_native import decode_native_capture

        if not any(
            state.venue.market_id == candidate.market_id
            and set(candidate.mints) == {state.asset_a.mint, state.asset_b.mint}
            for capture in captures
            for state in decode_native_capture(capture).pools
        ):
            raise ValueError("candidate not included in verified native capture")
        record = {
            "kind": "candidate_verification",
            "candidate_id": candidate.identity,
            "provenance": provenance,
            "verification_evidence_id": verification_id,
            "classification": (
                "ROOTED_REFERENCE" if body["quorum"]["accepted"] else "DISCOVERY_ONLY"
            ),
            "quality_state": body["quorum"]["reason"],
            "exact_state_ready": False,
        }
        self.evidence.append("verification", record, observed_at_ns=self.wall_ns())
        return record
