"""Chain-specific contracts; never relax the QPR Solana candidate domain."""

from dataclasses import asdict, dataclass
import re
import json
from urllib.parse import urlsplit

from src.provider_governance import ProviderEntitlement, ProviderOperation
from src.qualification_campaign.identity import digest
from src.research_economic_graph.registry import canonical_key, object_id


def uint(value, label, minimum=0, maximum=2**53 - 1):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("SUI_INVALID_" + label.upper())
    return value


def coin_type(value):
    return canonical_key("sui-mainnet", value)[1]


def sha(value):
    if not isinstance(value, str) or not re.fullmatch("[a-f0-9]{64}", value):
        raise ValueError("SUI_EXACT_SHA256_REQUIRED")
    return value


@dataclass(frozen=True)
class SuiCandidate:
    pool_id: str
    coin_types: tuple[str, str]
    venue: str

    def __post_init__(self):
        object.__setattr__(self, "pool_id", object_id(self.pool_id.lower()))
        types = tuple(sorted(coin_type(t) for t in self.coin_types))
        if (
            len(types) != 2
            or len(set(types)) != 2
            or self.venue not in ("deepbook", "aftermath", "cetus")
        ):
            raise ValueError("SUI_TWO_EXACT_COIN_TYPES_AND_VENUE_REQUIRED")
        object.__setattr__(self, "coin_types", types)

    @property
    def identity(self):
        return digest(
            {
                "chain": "sui-mainnet",
                "pool": self.pool_id,
                "coin_types": self.coin_types,
            }
        )


@dataclass(frozen=True)
class SuiReadRequest:
    method: str
    url: str
    purpose: str
    params: tuple[tuple[str, str], ...] = ()
    body: dict | None = None
    semantic_headers: tuple[tuple[str, str], ...] = (
        ("Accept", "application/json"),
        ("Content-Type", "application/json"),
        ("Accept-Encoding", "gzip,deflate,identity"),
    )

    def __post_init__(self):
        url = urlsplit(self.url)
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValueError("SUI_CREDENTIAL_FREE_HTTPS_REQUIRED")
        if self.method not in ("GET", "POST") or self.purpose not in (
            "pool-index",
            "structural-rates",
            "checkpoint",
            "checkpoint-object",
            "book-reference",
        ):
            raise ValueError("SUI_READ_ONLY_OPERATION_REQUIRED")
        if self.method == "GET" and self.body is not None:
            raise ValueError("SUI_GET_BODY_FORBIDDEN")
        if any(
            not isinstance(key, str)
            or not isinstance(value, str)
            or not key.isascii()
            or not value.isascii()
            or len(key) > 64
            or len(value) > 128
            for key, value in self.params
        ):
            raise ValueError("SUI_BOUNDED_PUBLIC_QUERY_STRINGS_REQUIRED")
        if self.purpose == "book-reference" and (
            self.method != "GET" or self.params != (("depth", "20"), ("level", "2"))
        ):
            raise ValueError("SUI_FINITE_REVIEWED_BOOK_REFERENCE_REQUIRED")
        if len(self.params) > 12 or len(dict(self.params)) != len(self.params):
            raise ValueError("SUI_BOUNDED_UNIQUE_PARAMETERS_REQUIRED")
        if len(str(self.body)) > 24_000:
            raise ValueError("SUI_BOUNDED_QUERY_REQUIRED")
        if self.semantic_headers != (
            ("Accept", "application/json"),
            ("Content-Type", "application/json"),
            ("Accept-Encoding", "gzip,deflate,identity"),
        ):
            raise ValueError("SUI_PINNED_PUBLIC_REQUEST_HEADERS_REQUIRED")
        # GraphQL is deliberately a finite read template, never arbitrary queries.
        if self.purpose in ("checkpoint", "checkpoint-object"):
            from .sources import CHECKPOINT_QUERY, OBJECT_QUERY

            expected = (
                CHECKPOINT_QUERY if self.purpose == "checkpoint" else OBJECT_QUERY
            )
            if not isinstance(self.body, dict) or self.body.get("query") != expected:
                raise ValueError("SUI_REVIEWED_GRAPHQL_READ_TEMPLATE_REQUIRED")

    @property
    def fingerprint(self):
        return digest(asdict(self))

    @property
    def serialized_body(self):
        return (
            None
            if self.body is None
            else json.dumps(
                self.body, ensure_ascii=False, separators=(",", ":"), allow_nan=False
            ).encode()
        )


@dataclass(frozen=True)
class SuiSourceProfile:
    profile_id: str
    provider: str
    operator: str
    correlation_group: str
    endpoint: str
    official_docs: str
    schema_pin: str
    method: str
    purpose: str
    source_kind: str
    request_limit: int = 12
    campaign_attempt_cap: int = 12
    window_seconds: int = 60
    smoke_only: bool = True
    credential_ref: str = "anonymous-public-read"
    credential_generation: str = "anonymous-v1"
    allowed_query_parameters: tuple[str, ...] = ()
    max_response_bytes: int = 1_048_576
    max_json_nodes: int = 20_000

    def __post_init__(self):
        for value in (self.endpoint, self.official_docs):
            url = urlsplit(value)
            if (
                url.scheme != "https"
                or not url.hostname
                or url.username
                or url.password
                or url.query
                or url.fragment
            ):
                raise ValueError("SUI_CREDENTIAL_FREE_HTTPS_REQUIRED")
        if self.method not in ("GET", "POST") or self.purpose not in (
            "pool-index",
            "structural-rates",
            "checkpoint",
            "book-reference",
        ):
            raise ValueError("SUI_READ_PROFILE_REQUIRED")
        if (
            self.source_kind
            not in (
                "deepbook",
                "aftermath",
                "cetus",
                "scallop",
                "graphql",
                "deepbook-book",
            )
            or ((self.purpose == "checkpoint") != (self.source_kind == "graphql"))
            or ((self.purpose == "structural-rates") != (self.source_kind == "scallop"))
        ):
            raise ValueError("SUI_PINNED_SOURCE_ADAPTER_KIND_REQUIRED")
        if (self.purpose == "book-reference") != (self.source_kind == "deepbook-book"):
            raise ValueError("SUI_PINNED_BOOK_REFERENCE_PROFILE_REQUIRED")
        uint(self.max_response_bytes, "response_byte_cap", 1, 4_194_304)
        uint(self.max_json_nodes, "json_node_cap", 1, 100_000)
        for text in (
            self.profile_id,
            self.provider,
            self.operator,
            self.correlation_group,
            self.official_docs,
            self.credential_ref,
            self.credential_generation,
        ):
            if not isinstance(text, str) or not text:
                raise ValueError("SUI_COMPLETE_PROVIDER_IDENTITY_REQUIRED")
        for field in ("provider", "operator", "correlation_group"):
            value = getattr(self, field)
            if value != value.strip():
                raise ValueError("SUI_CANONICAL_PROVIDER_IDENTITY_REQUIRED")
            object.__setattr__(self, field, value.lower())
        sha(self.schema_pin)
        for field in ("request_limit", "campaign_attempt_cap", "window_seconds"):
            uint(getattr(self, field), field, 1, 60)
        if type(self.smoke_only) is not bool:
            raise ValueError("SUI_SMOKE_CLASSIFICATION_REQUIRED")

    @property
    def generation(self):
        return digest(asdict(self))

    @property
    def hostname(self):
        return urlsplit(self.endpoint).hostname

    @property
    def quota_generation(self):
        # Source generations bind endpoint/schema/normalization independently.
        # Aliases of one external operator pool share the reviewed quota contract
        # generation so the durable dependency owner fences the same budget.
        return digest(
            {
                "contract": "gpr03.operator-quota.v1",
                "provider": self.provider,
                "operator": self.operator,
                "credential_ref": self.credential_ref,
                "credential_generation": self.credential_generation,
                "window_seconds": self.window_seconds,
                "request_limit": self.request_limit,
                "cost_unit_limit": self.request_limit,
                "spend_limit_micros": 0,
                "max_concurrency": 1,
            }
        )

    def entitlement(self, expires_at_epoch_seconds):
        return ProviderEntitlement(
            self.profile_id,
            self.quota_generation,
            frozenset({ProviderOperation.DISCOVERY, ProviderOperation.BACKFILL}),
            self.window_seconds,
            self.request_limit,
            self.request_limit,
            0,
            1,
            expires_at_epoch_seconds=expires_at_epoch_seconds,
            source_ref=self.official_docs,
            quota_pool_ref="gpr03:" + self.provider + ":" + self.operator,
            allowed_endpoints=(self.endpoint,),
            allowed_http_methods=frozenset({self.method}),
            allowed_query_parameters=frozenset(self.allowed_query_parameters),
            credential_ref=self.credential_ref,
            credential_generation=self.credential_generation,
        )
