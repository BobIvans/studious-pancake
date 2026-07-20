"""Official Pump protocol provenance guards for PR-048.

This module intentionally separates *official source provenance* from local
decoders and instruction builders.  A Pump family may be used for shadow
evidence only when the manifest pins a concrete upstream commit plus the
Git blob SHA of the IDL file used to derive layouts, discriminators and account
metas.  Live remains denied by the repository capability contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re
from typing import Any, Mapping


_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX16 = re.compile(r"^[0-9a-f]{16}$")
_OFFICIAL_REPO_PREFIX = "https://github.com/pump-fun/pump-public-docs"


class PumpManifestStatus(StrEnum):
    OFFICIAL_PINNED_SHADOW = "OFFICIAL_PINNED_SHADOW"
    DISABLED_UNVERIFIED_CONTRACT = "DISABLED_UNVERIFIED_CONTRACT"
    PENDING_OFFICIAL_PROVENANCE = "PENDING_OFFICIAL_PROVENANCE"


class PumpProvenanceError(ValueError):
    """Raised when a manifest family is not eligible for shadow execution."""


@dataclass(frozen=True, slots=True)
class PumpOfficialSource:
    family: str
    status: str
    official_docs_url: str
    idl_url: str
    upstream_commit: str
    idl_git_blob_sha: str
    program_id: str
    expected_owner: str
    discriminator_hex: str
    account_size: int
    instruction_names: tuple[str, ...]

    @classmethod
    def from_family(cls, raw: Mapping[str, Any]) -> "PumpOfficialSource":
        instructions = raw.get("instructions", {})
        instruction_names: list[str] = []
        if isinstance(instructions, Mapping):
            instruction_names = [str(name) for name in instructions]
        return cls(
            family=str(raw.get("family", "")),
            status=str(raw.get("status", "")),
            official_docs_url=str(raw.get("official_docs_url", "")),
            idl_url=str(raw.get("idl_url", "")),
            upstream_commit=str(raw.get("upstream_commit", raw.get("upstream_ref", ""))),
            idl_git_blob_sha=str(raw.get("idl_git_blob_sha", "")),
            program_id=str(raw.get("program_id", "")),
            expected_owner=str(raw.get("expected_owner", raw.get("program_id", ""))),
            discriminator_hex=str(raw.get("discriminator_hex", "")),
            account_size=int(raw.get("account_size", 0)),
            instruction_names=tuple(instruction_names),
        )

    def validation_errors(self) -> tuple[str, ...]:
        errors: list[str] = []
        if self.status != PumpManifestStatus.OFFICIAL_PINNED_SHADOW.value:
            errors.append(f"status={self.status or '<missing>'}")
        if not self.official_docs_url.startswith(_OFFICIAL_REPO_PREFIX):
            errors.append("official_docs_url_not_pump_public_docs")
        if not self.idl_url.startswith(_OFFICIAL_REPO_PREFIX):
            errors.append("idl_url_not_pump_public_docs")
        if not _HEX40.fullmatch(self.upstream_commit):
            errors.append("upstream_commit_not_40_hex")
        if not _HEX40.fullmatch(self.idl_git_blob_sha):
            errors.append("idl_git_blob_sha_not_40_hex")
        if not self.program_id or self.expected_owner != self.program_id:
            errors.append("program_owner_mismatch")
        if not _HEX16.fullmatch(self.discriminator_hex):
            errors.append("account_discriminator_not_8_bytes")
        if self.account_size <= 8:
            errors.append("account_size_too_small")
        if not self.instruction_names:
            errors.append("no_instructions_declared")
        return tuple(errors)

    def validate_shadow_ready(self) -> None:
        errors = self.validation_errors()
        if errors:
            raise PumpProvenanceError(
                "Pump manifest family is not official-pinned shadow eligible: "
                + ", ".join(errors)
            )


def provenance_from_family(raw: Mapping[str, Any]) -> PumpOfficialSource:
    return PumpOfficialSource.from_family(raw)


def manifest_shadow_errors(raw: Mapping[str, Any]) -> tuple[str, ...]:
    families = raw.get("families", ())
    if not isinstance(families, list):
        return ("families_not_list",)
    errors: list[str] = []
    for family in families:
        if not isinstance(family, Mapping):
            errors.append("family_not_mapping")
            continue
        source = PumpOfficialSource.from_family(family)
        for error in source.validation_errors():
            errors.append(f"{source.family or '<unknown>'}:{error}")
    return tuple(errors)
