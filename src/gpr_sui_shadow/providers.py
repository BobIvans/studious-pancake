"""Typed evidence requirements for independent non-smoke Sui state providers.

The offline contract proves checkpoint consistency and object-version
provenance across two independent governed providers whose retained captures
were already reconstructed by the HARD_BOUND gate. It defines what a binding
must pin (transport kind, endpoint, schema, reviewed genesis, non-smoke
classification) before any checkpoint/object evidence can be attached to it.

Live binding of external gRPC/GraphQL endpoints is NOT authorized in this
slice: the typed verdict is always ``BLOCKED`` with reason
``LIVE_SUI_PROVIDERS_NOT_AUTHORIZED`` until a human operator configures and
separately authorizes those providers. There is no code path that returns an
authorized live binding offline; unknown providers are never treated as zero.
"""

from dataclasses import asdict, dataclass
from urllib.parse import urlsplit

from src.qualification_campaign.identity import digest
from .models import object_id, sha, uint

LIVE_SUI_PROVIDERS_BLOCKED = "LIVE_SUI_PROVIDERS_NOT_AUTHORIZED"
PROVIDER_TRANSPORTS = ("graphql", "grpc")
# Match the reviewed SuiSourceProfile transport bounds; a binding may only be
# as wide as a governed read profile.
MAX_BINDING_RESPONSE_BYTES = 4_194_304
MAX_BINDING_JSON_NODES = 100_000
MAX_TEXT = 128


@dataclass(frozen=True)
class CheckpointProviderBinding:
    """One reviewed non-smoke state provider transport binding."""

    profile_id: str
    provider: str
    operator: str
    correlation_group: str
    transport: str
    endpoint: str
    schema_pin: str
    genesis_chain_identifier: str
    max_response_bytes: int = 1_048_576
    max_json_nodes: int = 20_000
    smoke_only: bool = False

    def __post_init__(self):
        for field in (
            "profile_id",
            "provider",
            "operator",
            "correlation_group",
            "genesis_chain_identifier",
        ):
            value = getattr(self, field)
            if not isinstance(value, str) or not value or value != value.strip():
                raise ValueError("SUI_CANONICAL_PROVIDER_BINDING_IDENTITY_REQUIRED")
            if len(value) > MAX_TEXT:
                raise ValueError("SUI_CANONICAL_PROVIDER_BINDING_IDENTITY_REQUIRED")
        for field in ("provider", "operator", "correlation_group"):
            value = getattr(self, field)
            if value != value.lower():
                raise ValueError("SUI_CANONICAL_PROVIDER_BINDING_IDENTITY_REQUIRED")
            object.__setattr__(self, field, value)
        if self.transport not in PROVIDER_TRANSPORTS:
            raise ValueError("SUI_PROVIDER_TRANSPORT_KIND_UNSUPPORTED")
        url = urlsplit(self.endpoint)
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValueError("SUI_CREDENTIAL_FREE_HTTPS_REQUIRED")
        sha(self.schema_pin)
        uint(
            self.max_response_bytes,
            "binding_response_cap",
            1,
            MAX_BINDING_RESPONSE_BYTES,
        )
        uint(self.max_json_nodes, "binding_json_node_cap", 1, MAX_BINDING_JSON_NODES)
        if self.smoke_only is not False:
            raise ValueError("SUI_NONSMOKE_PROVIDER_BINDING_REQUIRED")

    @property
    def generation(self):
        return digest(asdict(self))


@dataclass(frozen=True)
class CheckpointConsistencyEvidence:
    """Checkpoint/object facts reconstructed from one retained capture."""

    binding_generation: str
    capture_ref: str
    chain_identifier: str
    checkpoint_sequence: int
    checkpoint_digest: str
    object_id: str
    object_version: int
    object_digest: str
    payload_sha256: str
    observed_at_ns: int
    available_at_ns: int

    def __post_init__(self):
        sha(self.binding_generation)
        sha(self.capture_ref)
        sha(self.payload_sha256)
        if (
            not isinstance(self.chain_identifier, str)
            or not self.chain_identifier
            or len(self.chain_identifier) > MAX_TEXT
        ):
            raise ValueError("SUI_GENESIS_CHAIN_IDENTIFIER_REQUIRED")
        uint(self.checkpoint_sequence, "checkpoint_sequence", 1)
        for name in ("checkpoint_digest", "object_digest"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value or len(value) > MAX_TEXT:
                raise ValueError("SUI_PROVIDER_" + name.upper() + "_REQUIRED")
        object_id(self.object_id)
        uint(self.object_version, "object_version", 1)
        uint(self.observed_at_ns, "observed_ns", 1, 2**63 - 1)
        uint(self.available_at_ns, "available_ns", 1, 2**63 - 1)
        if self.available_at_ns < self.observed_at_ns:
            raise ValueError("SUI_PROVIDER_EVIDENCE_TIME_ORDER_REQUIRED")


@dataclass(frozen=True)
class OfflinePairVerdict:
    status: str
    checkpoint_sequence: int
    checkpoint_digest: str
    object_id: str
    object_version: int
    object_digest: str
    binding_generations: tuple[str, str]
    payload_sha256: tuple[str, str]


@dataclass(frozen=True)
class LiveBindingVerdict:
    status: str
    reason: str
    offline: OfflinePairVerdict


def require_independent_pair(bindings):
    if len(bindings) != 2 or len(set(bindings)) != 2:
        raise ValueError("SUI_TWO_INDEPENDENT_PROVIDER_BINDINGS_REQUIRED")
    for field in ("profile_id", "provider", "operator", "correlation_group"):
        # profile_id is case-significant; governed identities are canonical.
        values = [getattr(b, field) for b in bindings]
        if len(set(values)) != 2:
            raise ValueError("SUI_CORRELATED_PROVIDERS_BLOCKED")
    return tuple(sorted(bindings, key=lambda b: b.generation))


def verify_offline_pair(bindings, evidences):
    """Prove checkpoint consistency and object-version provenance offline."""
    ordered = require_independent_pair(bindings)
    if len(evidences) != 2 or len(set(evidences)) != 2:
        raise ValueError("SUI_TWO_PROVIDER_EVIDENCE_RECORDS_REQUIRED")
    for binding, evidence in zip(ordered, evidences, strict=True):
        if evidence.binding_generation != binding.generation:
            raise ValueError("SUI_PROVIDER_EVIDENCE_BINDING_MISMATCH")
        if evidence.chain_identifier != binding.genesis_chain_identifier:
            raise ValueError("SUI_GENESIS_BINDING_MISMATCH")
    first, second = evidences
    if (
        first.chain_identifier != second.chain_identifier
        or first.checkpoint_sequence != second.checkpoint_sequence
        or first.checkpoint_digest != second.checkpoint_digest
    ):
        raise ValueError("SUI_CHECKPOINT_CONSISTENCY_MISMATCH")
    if (
        first.object_id != second.object_id
        or first.object_version != second.object_version
        or first.object_digest != second.object_digest
    ):
        raise ValueError("SUI_OBJECT_VERSION_PROVENANCE_MISMATCH")
    return OfflinePairVerdict(
        status="OFFLINE_CONSISTENT",
        checkpoint_sequence=first.checkpoint_sequence,
        checkpoint_digest=first.checkpoint_digest,
        object_id=first.object_id,
        object_version=first.object_version,
        object_digest=first.object_digest,
        binding_generations=(ordered[0].generation, ordered[1].generation),
        payload_sha256=(first.payload_sha256, second.payload_sha256),
    )


def live_binding_verdict(bindings, evidences):
    """Offline-verifiable only: live provider binding is never authorized here.

    The verdict is deterministic: after the offline pair is proven consistent,
    the live status stays ``BLOCKED`` with the typed reason. External provider
    authorization requires an operator action outside this repository slice;
    no environment variable, credential or fixture can flip this verdict.
    """
    offline = verify_offline_pair(bindings, evidences)
    return LiveBindingVerdict(
        status="BLOCKED",
        reason=LIVE_SUI_PROVIDERS_BLOCKED,
        offline=offline,
    )
