"""Reviewed provider identity and physical read quota, no credential values."""

from dataclasses import asdict, dataclass
from importlib import resources
import json
from urllib.parse import urlsplit

from src.provider_governance import ProviderEntitlement, ProviderOperation
from .identity import digest

READ_RPC_METHODS = frozenset(
    {"getGenesisHash", "getMultipleAccounts", "getBlock", "getVersion", "getSlot"}
)


@dataclass(frozen=True)
class ProviderProfile:
    profile_id: str
    provider: str
    operator: str
    correlation_group: str
    endpoint: str
    official_docs: str
    credential_ref: str = "anonymous-public-read"
    credential_generation: str = "anonymous-v1"
    auth_header: str | None = None
    request_limit: int = 12
    window_seconds: int = 60
    campaign_attempt_cap: int = 100
    smoke_only: bool = False
    role: str = "rpc"
    allowed_query_parameters: tuple[str, ...] = ()
    schema_version: str = "prequal.provider-profile.v1"

    def __post_init__(self):
        for field in (
            "profile_id",
            "provider",
            "operator",
            "correlation_group",
            "official_docs",
            "credential_ref",
            "credential_generation",
        ):
            if (
                not isinstance(getattr(self, field), str)
                or not getattr(self, field).strip()
            ):
                raise ValueError("nonempty provider identity required: " + field)
        for value in (self.endpoint, self.official_docs):
            parsed = urlsplit(value)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("credential-free HTTPS endpoint/docs required")
        for field in ("request_limit", "window_seconds", "campaign_attempt_cap"):
            if type(getattr(self, field)) is not int or getattr(self, field) <= 0:
                raise ValueError("bounded positive quota required")
        if (
            self.role not in ("rpc", "discovery")
            or self.schema_version != "prequal.provider-profile.v1"
        ):
            raise ValueError("unsupported provider role/schema")
        if self.auth_header not in (None, "Authorization", "x-api-key"):
            raise ValueError("unsupported auth header")
        if type(self.smoke_only) is not bool:
            raise ValueError("smoke_only must be boolean")
        object.__setattr__(
            self, "allowed_query_parameters", tuple(self.allowed_query_parameters)
        )

    @property
    def generation(self):
        return digest(asdict(self))

    @property
    def hostname(self):
        return urlsplit(self.endpoint).hostname

    def entitlement(self, *, expires_at_epoch_seconds: int):
        return ProviderEntitlement(
            provider_id=self.profile_id,
            generation=self.generation,
            allowed_operations=frozenset(
                {ProviderOperation.BACKFILL, ProviderOperation.DISCOVERY}
            ),
            window_seconds=self.window_seconds,
            request_limit=self.request_limit,
            cost_unit_limit=self.request_limit,
            spend_limit_micros=0,
            max_concurrency=1,
            expires_at_epoch_seconds=expires_at_epoch_seconds,
            source_ref=self.official_docs,
            quota_pool_ref="campaign:" + self.provider + ":" + self.operator,
            allowed_endpoints=(self.endpoint,),
            allowed_http_methods=frozenset({"POST" if self.role == "rpc" else "GET"}),
            allowed_rpc_methods=READ_RPC_METHODS if self.role == "rpc" else frozenset(),
            allowed_query_parameters=frozenset(self.allowed_query_parameters),
            credential_ref=self.credential_ref,
            credential_generation=self.credential_generation,
        )


def public_rpc_profile():
    return ProviderProfile(
        **json.loads(
            resources.files("src.resources")
            .joinpath("qualification_public_rpc.json")
            .read_text()
        )
    )
