"""Installed CORE-V1 evidence resolver.

The resolver validates immutable profile/lender/deployment identities from an
operator-provided evidence manifest and wires only statically reviewed code.
It never dynamically imports code, constructs a signer/sender, or turns a
manifest flag into network qualification.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from src.config.runtime import RuntimeConfig
from src.execution.agg03_financing_decoder import (
    JupiterLendSlumlordRepaymentDecoder,
    decoder_artifact_sha256,
)
from src.lending.agg03_financing_ports import (
    JupiterLendFinancingPort,
    SlumlordFinancingPort,
)
from src.lending.financing import FinancingEvidence
from src.lending.jupiter_lend import JUPITER_LEND_FLASHLOAN_PROGRAM_ID
from src.lending.slumlord import SLUMLORD_PROGRAM_ID
from src.planning.atomic_marginfi_jupiter import AtomicPlannerPolicy
from src.runtime.core_v1_composition import CoreV1Dependencies
from src.runtime.core_v1_materializer import (
    CORE_V1_BLOCKED_EXTERNAL,
    BlockedCoreV1DraftSource,
    CoreV1ReleaseProfile,
)

SCHEMA = "core-v1.financing-evidence-manifest.v1"
MANIFEST_ENV = "FLASHLOAN_CORE_V1_EVIDENCE_MANIFEST"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class _ResolverBlockedRpc:
    """No-network port retained until a governed RPC is supplied by deployment."""

    async def call(self, _method: str, _params: list[Any]) -> Any:
        raise RuntimeError(CORE_V1_BLOCKED_EXTERNAL)


@dataclass(frozen=True, slots=True)
class InstalledDependencyResolution:
    dependencies: CoreV1Dependencies | None
    blocker: str | None
    manifest_sha256: str | None = None

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
) -> InstalledDependencyResolution:
    """Validate installed evidence and return statically reviewed dependencies.

    Even a resolved manifest uses a blocked draft source and blocked RPC until
    deployment supplies current provider observations. This makes the installed
    generic composition reachable without fabricating external evidence.
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
    if not isinstance(payload, Mapping) or payload.get("schema_version") != SCHEMA:
        raise ValueError("CORE_V1_FINANCING_EVIDENCE_MANIFEST_SCHEMA_MISMATCH")
    if payload.get("profile_id") != profile.profile_id:
        raise ValueError("CORE_V1_FINANCING_MANIFEST_PROFILE_MISMATCH")
    if payload.get("profile_generation") != profile.profile_generation:
        raise ValueError("CORE_V1_FINANCING_MANIFEST_GENERATION_MISMATCH")

    primary = _identity(payload.get("primary"), "primary")
    rent = _identity(payload.get("rent"), "rent")
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
        rpc=_ResolverBlockedRpc(),
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
    )


__all__ = [
    "FinancingIdentity",
    "InstalledDependencyResolution",
    "MANIFEST_ENV",
    "SCHEMA",
    "resolve_installed_core_v1_dependencies",
]
