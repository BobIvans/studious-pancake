"""Installed CORE-V1 evidence resolver.

The resolver validates immutable profile/lender/deployment identities from an
operator-provided evidence manifest and wires only statically reviewed code.
It never dynamically imports code, constructs a signer/sender, or turns a
manifest flag into network qualification.

R08-step1 governed-RPC seam (composition-only): a deployment may supply ONE
governed RPC transport through :func:`resolve_installed_core_v1_dependencies`
(keyword-only ``governed_rpc_transport``). The transport is accepted ONLY when
the evidence manifest pins the matching ``governed_rpc`` descriptor (https,
credential-free, rooted endpoint identity + deployment generation). Absent
descriptor or absent transport keeps the historical ``_ResolverBlockedRpc``
default — no environment variable, capability flag or manifest flag alone can
produce a network-capable transport. The pinned descriptor fingerprint is
returned on the resolution so simulation evidence can be bound to it.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping
from urllib.parse import urlsplit

from src.config.runtime import RuntimeConfig
from src.execution.agg03_financing_decoder import (
    JupiterLendSlumlordRepaymentDecoder,
    decoder_artifact_sha256,
)
from src.execution.models import RpcClient
from src.lending.agg03_financing_ports import (
    JupiterLendFinancingPort,
    SlumlordFinancingPort,
)
from src.lending.financing import FinancingEvidence
from src.lending.jupiter_lend import JUPITER_LEND_FLASHLOAN_PROGRAM_ID
from src.lending.slumlord import SLUMLORD_PROGRAM_ID
from src.lending.sp_q01_protocol_admission import (
    validate_protocol_admission_receipt,
)
from src.planning.atomic_marginfi_jupiter import AtomicPlannerPolicy
from src.runtime.trusted_time import SystemTrustedTime, TrustedTime
from src.runtime.core_v1_composition import CoreV1Dependencies
from src.runtime.core_v1_materializer import (
    CORE_V1_BLOCKED_EXTERNAL,
    BlockedCoreV1DraftSource,
    CoreV1ReleaseProfile,
)

SCHEMA = "core-v1.financing-evidence-manifest.v2"
LEGACY_SCHEMA = "core-v1.financing-evidence-manifest.v1"
MANIFEST_ENV = "FLASHLOAN_CORE_V1_EVIDENCE_MANIFEST"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

CORE_V1_GOVERNED_RPC_DESCRIPTOR_REQUIRED = "CORE_V1_GOVERNED_RPC_DESCRIPTOR_REQUIRED"
CORE_V1_GOVERNED_RPC_TRANSPORT_REQUIRED = "CORE_V1_GOVERNED_RPC_TRANSPORT_REQUIRED"
CORE_V1_GOVERNED_RPC_DESCRIPTOR_INVALID = "CORE_V1_GOVERNED_RPC_DESCRIPTOR_INVALID"
CORE_V1_GOVERNED_RPC_TRANSPORT_INVALID = "CORE_V1_GOVERNED_RPC_TRANSPORT_INVALID"

_MAX_ENDPOINT_TEXT = 256


class _ResolverBlockedRpc:
    """No-network port retained until a governed RPC is supplied by deployment."""

    async def call(self, _method: str, _params: list[Any]) -> Any:
        raise RuntimeError(CORE_V1_BLOCKED_EXTERNAL)


@dataclass(frozen=True, slots=True)
class GovernedRpcDescriptor:
    """Manifest-pinned deployment RPC identity (R08-step1 seam).

    The descriptor is EVIDENCE, never authority: it pins WHERE a governed
    transport may terminate (https, credential-free, no query/fragment — the
    same credential-free discipline as the Sui provider bindings) and WHICH
    deployment generation it belongs to. The matching transport object is
    supplied separately by the deployment through the resolver argument, so
    no code path in this repository constructs a network transport.
    """

    endpoint: str
    deployment_generation: int

    def __post_init__(self) -> None:
        if not isinstance(self.endpoint, str) or not self.endpoint.strip():
            raise ValueError(CORE_V1_GOVERNED_RPC_DESCRIPTOR_INVALID)
        endpoint = self.endpoint.strip()
        if len(endpoint) > _MAX_ENDPOINT_TEXT:
            raise ValueError(CORE_V1_GOVERNED_RPC_DESCRIPTOR_INVALID)
        url = urlsplit(endpoint)
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValueError(CORE_V1_GOVERNED_RPC_DESCRIPTOR_INVALID)
        if url.path not in ("", "/"):
            raise ValueError(CORE_V1_GOVERNED_RPC_DESCRIPTOR_INVALID)
        object.__setattr__(self, "endpoint", endpoint)
        if (
            type(self.deployment_generation) is not int
            or self.deployment_generation < 1
        ):
            raise ValueError(CORE_V1_GOVERNED_RPC_DESCRIPTOR_INVALID)

    @classmethod
    def from_manifest(cls, raw: object) -> "GovernedRpcDescriptor":
        if not isinstance(raw, Mapping):
            raise ValueError(CORE_V1_GOVERNED_RPC_DESCRIPTOR_INVALID)
        return cls(
            endpoint=raw.get("endpoint"),  # type: ignore[arg-type]
            deployment_generation=raw.get("deployment_generation"),  # type: ignore[arg-type]
        )

    @property
    def fingerprint(self) -> str:
        """Stable identity hash binding simulation evidence to this transport."""
        return hashlib.sha256(
            json.dumps(
                {
                    "schema": "core-v1.governed-rpc-descriptor.v1",
                    "endpoint": self.endpoint,
                    "deployment_generation": self.deployment_generation,
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("utf-8")
        ).hexdigest()


def _validate_governed_rpc_transport(transport: RpcClient | None) -> RpcClient:
    """Accept ONE deployment-supplied callable transport; nothing else.

    The transport must already exist (deployment-owned object); this resolver
    constructs no network client of its own and never dials the endpoint.
    """
    if transport is None or not callable(getattr(transport, "call", None)):
        raise ValueError(CORE_V1_GOVERNED_RPC_TRANSPORT_INVALID)
    return transport


@dataclass(frozen=True, slots=True)
class InstalledDependencyResolution:
    dependencies: CoreV1Dependencies | None
    blocker: str | None
    manifest_sha256: str | None = None
    governed_rpc_fingerprint: str | None = None

    @property
    def resolved(self) -> bool:
        return self.dependencies is not None and self.blocker is None


@dataclass(frozen=True, slots=True)
class FinancingIdentity:
    lender_id: str
    program_id: str
    deployment_generation: int
    evidence_sha256: str
    decoder_identity: str
    decoder_generation: int
    qualified: bool


def _sha(value: object, label: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ValueError(f"CORE_V1_{label.upper()}_SHA256_INVALID")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"CORE_V1_{label.upper()}_REQUIRED")
    return value.strip()


def _identity(raw: object, label: str) -> FinancingIdentity:
    if not isinstance(raw, Mapping):
        raise ValueError(f"CORE_V1_{label.upper()}_IDENTITY_REQUIRED")
    lender = _text(raw.get("lender_id"), f"{label}_lender")
    program = _text(raw.get("program_id"), f"{label}_program")
    decoder = _text(raw.get("decoder_identity"), f"{label}_decoder_identity")
    generation = raw.get("deployment_generation")
    decoder_generation = raw.get("decoder_generation")
    if type(generation) is not int or generation < 1:
        raise ValueError(f"CORE_V1_{label.upper()}_GENERATION_INVALID")
    if type(decoder_generation) is not int or decoder_generation < 1:
        raise ValueError(f"CORE_V1_{label.upper()}_DECODER_GENERATION_INVALID")
    qualified = raw.get("qualified")
    if type(qualified) is not bool:
        raise ValueError(f"CORE_V1_{label.upper()}_QUALIFIED_BOOLEAN_REQUIRED")
    return FinancingIdentity(
        lender_id=lender,
        program_id=program,
        deployment_generation=generation,
        evidence_sha256=_sha(raw.get("evidence_sha256"), f"{label}_evidence"),
        decoder_identity=decoder,
        decoder_generation=decoder_generation,
        qualified=qualified,
    )


def _evidence(identity: FinancingIdentity) -> FinancingEvidence:
    return FinancingEvidence(
        lender_id=identity.lender_id,
        program_id=identity.program_id,
        deployment_generation=identity.deployment_generation,
        evidence_sha256=identity.evidence_sha256,
        decoder_identity=identity.decoder_identity,
        decoder_generation=identity.decoder_generation,
    )


def resolve_installed_core_v1_dependencies(
    profile: CoreV1ReleaseProfile,
    environment: Mapping[str, str],
    *,
    config: RuntimeConfig | None = None,
    trusted_time: TrustedTime | None = None,
    governed_rpc_transport: RpcClient | None = None,
) -> InstalledDependencyResolution:
    """Validate installed evidence and return statically reviewed dependencies.

    Even a resolved manifest uses a blocked draft source and blocked RPC until
    deployment supplies current provider observations. This makes the installed
    generic composition reachable without fabricating external evidence.

    R08-step1: ``governed_rpc_transport`` is the ONLY composition-only seam
    through which a deployment-supplied governed RPC replaces the blocked
    default. It is accepted only when the manifest pins the matching
    ``governed_rpc`` descriptor; any pairing mismatch is a typed error and an
    absent transport keeps ``_ResolverBlockedRpc`` exactly as before.
    """

    if profile.lender == "marginfi":
        return InstalledDependencyResolution(
            None,
            CORE_V1_BLOCKED_EXTERNAL,
            None,
        )

    raw_path = environment.get(MANIFEST_ENV, "").strip()
    if not raw_path:
        return InstalledDependencyResolution(
            None,
            "CORE_V1_FINANCING_EVIDENCE_MANIFEST_REQUIRED",
            None,
        )
    path = Path(raw_path).expanduser()
    raw_bytes = path.read_bytes()
    digest = hashlib.sha256(raw_bytes).hexdigest()
    payload = json.loads(raw_bytes)
    if not isinstance(payload, Mapping):
        raise ValueError("CORE_V1_FINANCING_EVIDENCE_MANIFEST_SCHEMA_MISMATCH")
    if payload.get("schema_version") == LEGACY_SCHEMA:
        return InstalledDependencyResolution(
            None,
            "CORE_V1_FINANCING_ADMISSION_RECEIPT_REQUIRED",
            digest,
        )
    if payload.get("schema_version") != SCHEMA:
        raise ValueError("CORE_V1_FINANCING_EVIDENCE_MANIFEST_SCHEMA_MISMATCH")
    if payload.get("profile_id") != profile.profile_id:
        raise ValueError("CORE_V1_FINANCING_MANIFEST_PROFILE_MISMATCH")
    if payload.get("profile_generation") != profile.profile_generation:
        raise ValueError("CORE_V1_FINANCING_MANIFEST_GENERATION_MISMATCH")

    # R08-step1 governed-RPC seam: descriptor/transport pairing is validated
    # BEFORE any qualification flow so mismatches fail loud and early.
    manifest_rpc_raw = payload.get("governed_rpc")
    governed_rpc_fingerprint: str | None = None
    rpc_port: RpcClient = _ResolverBlockedRpc()
    if manifest_rpc_raw is None:
        if governed_rpc_transport is not None:
            raise ValueError(CORE_V1_GOVERNED_RPC_DESCRIPTOR_REQUIRED)
    else:
        descriptor = GovernedRpcDescriptor.from_manifest(manifest_rpc_raw)
        if governed_rpc_transport is None:
            # Descriptor pinned but no deployment transport supplied: keep the
            # blocked default (fail-closed), never fabricate a transport.
            return InstalledDependencyResolution(
                None,
                CORE_V1_GOVERNED_RPC_TRANSPORT_REQUIRED,
                digest,
            )
        transport = _validate_governed_rpc_transport(governed_rpc_transport)
        governed_rpc_fingerprint = descriptor.fingerprint
        rpc_port = transport

    primary_raw = payload.get("primary")
    rent_raw = payload.get("rent")
    primary = _identity(primary_raw, "primary")
    rent = _identity(rent_raw, "rent")
    if (
        primary.lender_id != profile.lender
        or primary.deployment_generation != profile.profile_generation
        or primary.program_id != str(JUPITER_LEND_FLASHLOAN_PROGRAM_ID)
    ):
        raise ValueError("CORE_V1_PRIMARY_FINANCING_IDENTITY_MISMATCH")
    if rent.lender_id != "slumlord" or rent.program_id != str(SLUMLORD_PROGRAM_ID):
        raise ValueError("CORE_V1_RENT_FINANCING_IDENTITY_MISMATCH")
    if not primary.qualified:
        return InstalledDependencyResolution(
            None,
            "CORE_V1_PRIMARY_FINANCING_DEPLOYMENT_NOT_QUALIFIED",
            digest,
        )
    if not rent.qualified:
        return InstalledDependencyResolution(
            None,
            "CORE_V1_RENT_FINANCING_DEPLOYMENT_NOT_QUALIFIED",
            digest,
        )

    if not isinstance(primary_raw, Mapping) or not isinstance(rent_raw, Mapping):
        raise ValueError("CORE_V1_FINANCING_IDENTITY_REQUIRED")
    now_utc = (trusted_time or SystemTrustedTime()).snapshot().utc
    primary_admission = validate_protocol_admission_receipt(
        primary_raw.get("admission"),
        role="PRIMARY",
        now_utc=now_utc,
    )
    rent_admission = validate_protocol_admission_receipt(
        rent_raw.get("admission"),
        role="RENT",
        now_utc=now_utc,
    )
    if primary_admission.receipt_sha256 != primary.evidence_sha256:
        raise ValueError("CORE_V1_PRIMARY_FINANCING_EVIDENCE_RECEIPT_MISMATCH")
    if rent_admission.receipt_sha256 != rent.evidence_sha256:
        raise ValueError("CORE_V1_RENT_FINANCING_EVIDENCE_RECEIPT_MISMATCH")

    decoder_artifact = payload.get("repayment_decoder")
    if not isinstance(decoder_artifact, Mapping):
        return InstalledDependencyResolution(
            None,
            "CORE_V1_FINANCING_REPAYMENT_DECODER_EVIDENCE_REQUIRED",
            digest,
        )
    artifact_sha = _sha(
        decoder_artifact.get("artifact_sha256"),
        "repayment_decoder_artifact",
    )
    if decoder_artifact.get("qualified") is not True:
        return InstalledDependencyResolution(
            None,
            "CORE_V1_FINANCING_REPAYMENT_DECODER_NOT_QUALIFIED",
            digest,
        )
    if artifact_sha != decoder_artifact_sha256():
        raise ValueError("CORE_V1_FINANCING_REPAYMENT_DECODER_ARTIFACT_MISMATCH")
    if config is None:
        return InstalledDependencyResolution(
            None,
            "CORE_V1_RUNTIME_CONFIG_REQUIRED",
            digest,
        )

    release_id = _text(payload.get("release_id"), "release_id")
    policy_bundle_hash = _sha(payload.get("policy_bundle_hash"), "policy_bundle")
    primary_evidence = _evidence(primary)
    rent_evidence = _evidence(rent)
    primary_port = JupiterLendFinancingPort(primary_evidence)
    rent_port = SlumlordFinancingPort(rent_evidence)
    decoder = JupiterLendSlumlordRepaymentDecoder(
        primary_evidence,
        rent_evidence,
    )
    allowed_program_ids = tuple(
        dict.fromkeys(
            (
                *config.allowlist.program_ids,
                primary.program_id,
                rent.program_id,
            )
        )
    )
    dependencies = CoreV1Dependencies(
        release_id=release_id,
        policy_bundle_hash=policy_bundle_hash,
        draft_source=BlockedCoreV1DraftSource(),
        rpc=rpc_port,
        marginfi_provider=None,
        planner_policy=AtomicPlannerPolicy(
            allowed_program_ids=allowed_program_ids,
        ),
        financing_port=primary_port,
        financing_evidence=primary_evidence,
        financing_repayment_decoder=decoder,
        rent_financing_port=rent_port,
        rent_financing_evidence=rent_evidence,
    )
    return InstalledDependencyResolution(
        dependencies,
        "CORE_V1_PROVIDER_DRAFT_SOURCE_EXTERNAL",
        digest,
        governed_rpc_fingerprint,
    )


__all__ = [
    "CORE_V1_GOVERNED_RPC_DESCRIPTOR_INVALID",
    "CORE_V1_GOVERNED_RPC_DESCRIPTOR_REQUIRED",
    "CORE_V1_GOVERNED_RPC_TRANSPORT_INVALID",
    "CORE_V1_GOVERNED_RPC_TRANSPORT_REQUIRED",
    "FinancingIdentity",
    "GovernedRpcDescriptor",
    "InstalledDependencyResolution",
    "LEGACY_SCHEMA",
    "MANIFEST_ENV",
    "SCHEMA",
    "resolve_installed_core_v1_dependencies",
]
