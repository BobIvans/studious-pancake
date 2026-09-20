"""Installed CORE-V1 evidence resolver.

The resolver is intentionally data-only and fail closed. It validates immutable
profile/lender/deployment identities from an operator-provided evidence manifest,
but it does not dynamically import protocol code, construct a signer/sender, or
pretend a recorded digest is a qualified repayment decoder.

A future externally-qualified decoder factory can extend this boundary without
changing the installed runtime entrypoint again.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Mapping

from src.lending.jupiter_lend import JUPITER_LEND_FLASHLOAN_PROGRAM_ID
from src.lending.slumlord import SLUMLORD_PROGRAM_ID
from src.runtime.core_v1_composition import CoreV1Dependencies
from src.runtime.core_v1_materializer import CoreV1ReleaseProfile

SCHEMA = "core-v1.financing-evidence-manifest.v1"
MANIFEST_ENV = "FLASHLOAN_CORE_V1_EVIDENCE_MANIFEST"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


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


def _sha(value: object, label: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ValueError(f"CORE_V1_{label.upper()}_SHA256_INVALID")
    return value


def _identity(raw: object, label: str) -> FinancingIdentity:
    if not isinstance(raw, Mapping):
        raise ValueError(f"CORE_V1_{label.upper()}_IDENTITY_REQUIRED")
    lender = raw.get("lender_id")
    program = raw.get("program_id")
    decoder = raw.get("decoder_identity")
    generation = raw.get("deployment_generation")
    decoder_generation = raw.get("decoder_generation")
    if not isinstance(lender, str) or not lender.strip():
        raise ValueError(f"CORE_V1_{label.upper()}_LENDER_REQUIRED")
    if not isinstance(program, str) or not program.strip():
        raise ValueError(f"CORE_V1_{label.upper()}_PROGRAM_REQUIRED")
    if not isinstance(decoder, str) or not decoder.strip():
        raise ValueError(f"CORE_V1_{label.upper()}_DECODER_IDENTITY_REQUIRED")
    if type(generation) is not int or generation < 1:
        raise ValueError(f"CORE_V1_{label.upper()}_GENERATION_INVALID")
    if type(decoder_generation) is not int or decoder_generation < 1:
        raise ValueError(f"CORE_V1_{label.upper()}_DECODER_GENERATION_INVALID")
    return FinancingIdentity(
        lender_id=lender,
        program_id=program,
        deployment_generation=generation,
        evidence_sha256=_sha(raw.get("evidence_sha256"), f"{label}_evidence"),
        decoder_identity=decoder,
        decoder_generation=decoder_generation,
    )


def resolve_installed_core_v1_dependencies(
    profile: CoreV1ReleaseProfile,
    environment: Mapping[str, str],
) -> InstalledDependencyResolution:
    """Validate installed evidence identity and return the next exact blocker."""

    if profile.lender == "marginfi":
        return InstalledDependencyResolution(
            None,
            "CORE_V1_BLOCKED_EXTERNAL",
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
    if (
        rent.lender_id != "slumlord"
        or rent.program_id != str(SLUMLORD_PROGRAM_ID)
    ):
        raise ValueError("CORE_V1_RENT_FINANCING_IDENTITY_MISMATCH")

    decoder_artifact = payload.get("repayment_decoder")
    if not isinstance(decoder_artifact, Mapping):
        return InstalledDependencyResolution(
            None,
            "CORE_V1_FINANCING_REPAYMENT_DECODER_EVIDENCE_REQUIRED",
            digest,
        )
    _sha(decoder_artifact.get("artifact_sha256"), "repayment_decoder_artifact")
    if decoder_artifact.get("qualified") is not True:
        return InstalledDependencyResolution(
            None,
            "CORE_V1_FINANCING_REPAYMENT_DECODER_NOT_QUALIFIED",
            digest,
        )

    # Qualification evidence is necessary but not sufficient. The repository
    # deliberately has no dynamic-code loading path; until a reviewed decoder
    # implementation is statically installed, the runtime stays default-off.
    return InstalledDependencyResolution(
        None,
        "CORE_V1_FINANCING_REPAYMENT_DECODER_IMPLEMENTATION_REQUIRED",
        digest,
    )


__all__ = [
    "FinancingIdentity",
    "InstalledDependencyResolution",
    "MANIFEST_ENV",
    "SCHEMA",
    "resolve_installed_core_v1_dependencies",
]
