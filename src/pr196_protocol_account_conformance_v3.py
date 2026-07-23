"""PR-196 V3 protocol/account conformance acceptance contract.

This module is intentionally offline and sender-free. It gives the revised
PR-196 roadmap a single typed gate for provider/protocol/account evidence:
canonical chain identity, Token-2022 fail-closed policy, wSOL/native SOL
separation, packaged provenance, rooted account attestations, bounded provider
fixtures and Jupiter/ALT/blockhash validation.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
import hashlib
import json
import re
from typing import Mapping, Self

SCHEMA_VERSION = "pr196.protocol-account-conformance-v3.v1"
OFFICIAL_TOKEN_2022_PROGRAM_ID = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
NATIVE_SOL_SENTINEL = "11111111111111111111111111111111"
WSOL_MINT = "So11111111111111111111111111111111111111112"

_FALSE_TOKEN_2022_PROGRAM_IDS: frozenset[str] = frozenset(
    {
        "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPFJmNchboJLH2e2UrfW",
        "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEPw1N1qEHxZC6kzNRQdB",
    }
)
_EVIDENCE_REF = re.compile(r"^(evidence|fixtures|tests|docs)/[A-Za-z0-9._/@+=:-]+$")


class PR196ProtocolConformanceError(ValueError):
    """Raised when a PR-196 protocol-conformance claim is malformed."""


@dataclass(frozen=True, slots=True)
class PR196Requirement:
    """One acceptance invariant owned by revised V3 PR-196."""

    requirement_id: str
    finding_ids: tuple[str, ...]
    description: str
    required_claim_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PR196ProtocolConformanceClaim:
    """Boolean evidence claim for the PR-196 conformance boundary."""

    canonical_chain_registry_used: bool = False
    token_2022_program_id_matches_official: bool = False
    false_token_2022_literals_rejected: bool = False
    native_sol_and_wsol_are_distinct_types: bool = False
    marginfi_provenance_packaged_and_mandatory: bool = False
    rooted_account_mint_alt_oracle_snapshots: bool = False
    token_2022_default_fail_closed: bool = False
    marginfi_kamino_layouts_pinned: bool = False
    bounded_provider_bodies_and_redirects: bool = False
    dns_public_ip_pinning: bool = False
    retry_quota_budget_is_typed_and_shared: bool = False
    jupiter_build_alt_blockhash_semantics_validated: bool = False
    credentialed_fixtures_reviewed: bool = False
    provider_registry_signed: bool = False
    evidence_refs: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> Self:
        """Build a strictly validated claim from JSON-like data."""

        allowed = {field.name for field in fields(cls)}
        unknown = sorted(set(payload).difference(allowed))
        if unknown:
            raise PR196ProtocolConformanceError(
                "unknown PR-196 protocol-conformance claim fields: "
                + ", ".join(unknown)
            )

        defaults = cls()
        values: dict[str, object] = {}
        for field in fields(cls):
            raw = payload.get(field.name, getattr(defaults, field.name))
            if field.name == "evidence_refs":
                values[field.name] = _evidence_refs(raw)
            elif not isinstance(raw, bool):
                raise PR196ProtocolConformanceError(
                    f"claim field {field.name!r} must be boolean"
                )
            else:
                values[field.name] = raw
        return cls(**values)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class PR196RequirementResult:
    """Evaluation result for one PR-196 requirement."""

    requirement_id: str
    finding_ids: tuple[str, ...]
    satisfied: bool
    missing_claim_fields: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "requirement_id": self.requirement_id,
            "finding_ids": list(self.finding_ids),
            "satisfied": self.satisfied,
            "missing_claim_fields": list(self.missing_claim_fields),
        }


@dataclass(frozen=True, slots=True)
class PR196ProtocolConformanceReport:
    """Deterministic offline evidence for PR-196 protocol conformance."""

    schema_version: str
    ready: bool
    reason_codes: tuple[str, ...]
    claim_hash: str
    requirement_results: tuple[PR196RequirementResult, ...]
    live_execution_allowed: bool = False
    signer_or_sender_allowed: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "ready": self.ready,
            "reason_codes": list(self.reason_codes),
            "claim_hash": self.claim_hash,
            "live_execution_allowed": self.live_execution_allowed,
            "signer_or_sender_allowed": self.signer_or_sender_allowed,
            "canonical_program_ids": {
                "token_2022": OFFICIAL_TOKEN_2022_PROGRAM_ID,
                "native_sol_sentinel": NATIVE_SOL_SENTINEL,
                "wsol_mint": WSOL_MINT,
            },
            "requirement_results": [
                item.to_dict() for item in self.requirement_results
            ],
        }

    def to_json(self) -> str:
        """Serialize report deterministically."""

        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"


REQUIREMENTS: tuple[PR196Requirement, ...] = (
    PR196Requirement(
        requirement_id="CANONICAL_CHAIN_PROGRAM_IDENTITY",
        finding_ids=("F-129", "F-130"),
        description="Program and asset identity must come from one canonical registry.",
        required_claim_fields=(
            "canonical_chain_registry_used",
            "token_2022_program_id_matches_official",
            "false_token_2022_literals_rejected",
            "native_sol_and_wsol_are_distinct_types",
        ),
    ),
    PR196Requirement(
        requirement_id="PACKAGED_MARGINFI_PROVENANCE",
        finding_ids=("F-139",),
        description="MarginFi/P0 provenance must be packaged or supplied as a required hash-bound artifact.",
        required_claim_fields=("marginfi_provenance_packaged_and_mandatory",),
    ),
    PR196Requirement(
        requirement_id="ROOTED_ACCOUNT_MINT_ORACLE_ATTESTATION",
        finding_ids=("F-106", "F-107", "F-108", "F-109", "F-110", "F-129"),
        description="Accepted accounts, mints, ALTs and oracle snapshots are rooted and owner/layout attested.",
        required_claim_fields=(
            "rooted_account_mint_alt_oracle_snapshots",
            "token_2022_default_fail_closed",
            "marginfi_kamino_layouts_pinned",
        ),
    ),
    PR196Requirement(
        requirement_id="BOUNDED_PROVIDER_TRANSPORT_AND_QUOTA",
        finding_ids=("F-020", "F-021", "F-022", "F-023", "F-063", "F-067"),
        description="Provider responses, redirects, DNS, retries and quotas are bounded before planning.",
        required_claim_fields=(
            "bounded_provider_bodies_and_redirects",
            "dns_public_ip_pinning",
            "retry_quota_budget_is_typed_and_shared",
        ),
    ),
    PR196Requirement(
        requirement_id="JUPITER_BUILD_ALT_BLOCKHASH_CONTRACT",
        finding_ids=("F-111", "F-112", "F-113", "F-114", "F-115"),
        description="Jupiter build, route, ALT and blockhash metadata are semantically validated.",
        required_claim_fields=("jupiter_build_alt_blockhash_semantics_validated",),
    ),
    PR196Requirement(
        requirement_id="REVIEWED_CREDENTIALED_CONFORMANCE_FIXTURES",
        finding_ids=("F-116", "F-117", "F-118", "F-119", "F-120", "F-121", "F-122", "F-123"),
        description="Credentialed read-only conformance fixtures and registry generation are reviewed and signed.",
        required_claim_fields=(
            "credentialed_fixtures_reviewed",
            "provider_registry_signed",
        ),
    ),
)


def evaluate_pr196_protocol_conformance(
    claim: PR196ProtocolConformanceClaim,
    *,
    live_execution_allowed: bool = False,
    signer_or_sender_allowed: bool = False,
) -> PR196ProtocolConformanceReport:
    """Evaluate the revised PR-196 protocol/account conformance gate."""

    reason_codes: list[str] = []
    results: list[PR196RequirementResult] = []

    for requirement in REQUIREMENTS:
        missing = tuple(
            field_name
            for field_name in requirement.required_claim_fields
            if not bool(getattr(claim, field_name))
        )
        if missing:
            reason_codes.append(f"{requirement.requirement_id}:MISSING_PROOF")
        results.append(
            PR196RequirementResult(
                requirement_id=requirement.requirement_id,
                finding_ids=requirement.finding_ids,
                satisfied=not missing,
                missing_claim_fields=missing,
            )
        )

    if live_execution_allowed:
        reason_codes.append("LIVE_EXECUTION_NOT_ALLOWED_IN_PR196")
    if signer_or_sender_allowed:
        reason_codes.append("SIGNER_OR_SENDER_NOT_ALLOWED_IN_PR196")
    if NATIVE_SOL_SENTINEL == WSOL_MINT:
        reason_codes.append("NATIVE_SOL_AND_WSOL_IDENTITY_COLLAPSED")
    if OFFICIAL_TOKEN_2022_PROGRAM_ID in _FALSE_TOKEN_2022_PROGRAM_IDS:
        reason_codes.append("FALSE_TOKEN_2022_LIST_CONTAINS_OFFICIAL_ID")

    return PR196ProtocolConformanceReport(
        schema_version=SCHEMA_VERSION,
        ready=not reason_codes,
        reason_codes=tuple(reason_codes),
        claim_hash=_claim_hash(claim),
        requirement_results=tuple(results),
        live_execution_allowed=live_execution_allowed,
        signer_or_sender_allowed=signer_or_sender_allowed,
    )


def complete_offline_claim(
    *,
    evidence_refs: tuple[str, ...],
) -> PR196ProtocolConformanceClaim:
    """Return a complete sender-free claim for focused tests and examples."""

    refs = _evidence_refs(evidence_refs)
    if not refs:
        raise PR196ProtocolConformanceError("complete PR-196 claim requires evidence_refs")
    return PR196ProtocolConformanceClaim(
        canonical_chain_registry_used=True,
        token_2022_program_id_matches_official=True,
        false_token_2022_literals_rejected=True,
        native_sol_and_wsol_are_distinct_types=True,
        marginfi_provenance_packaged_and_mandatory=True,
        rooted_account_mint_alt_oracle_snapshots=True,
        token_2022_default_fail_closed=True,
        marginfi_kamino_layouts_pinned=True,
        bounded_provider_bodies_and_redirects=True,
        dns_public_ip_pinning=True,
        retry_quota_budget_is_typed_and_shared=True,
        jupiter_build_alt_blockhash_semantics_validated=True,
        credentialed_fixtures_reviewed=True,
        provider_registry_signed=True,
        evidence_refs=refs,
    )


def false_token_2022_program_ids() -> tuple[str, ...]:
    """Return the known incorrect Token-2022 literals that must be rejected."""

    return tuple(sorted(_FALSE_TOKEN_2022_PROGRAM_IDS))


def assert_token_2022_program_id(value: str) -> None:
    """Fail unless *value* is the canonical official Token-2022 program id."""

    if value in _FALSE_TOKEN_2022_PROGRAM_IDS:
        raise PR196ProtocolConformanceError("known false Token-2022 program id")
    if value != OFFICIAL_TOKEN_2022_PROGRAM_ID:
        raise PR196ProtocolConformanceError("non-canonical Token-2022 program id")


def report_from_mapping(payload: Mapping[str, object]) -> PR196ProtocolConformanceReport:
    """Convenience entrypoint for JSON/YAML-driven CI checks."""

    return evaluate_pr196_protocol_conformance(
        PR196ProtocolConformanceClaim.from_mapping(payload)
    )


def render_report_json(payload: Mapping[str, object]) -> str:
    """Render a deterministic PR-196 conformance report from a mapping."""

    return report_from_mapping(payload).to_json()


def _claim_hash(claim: PR196ProtocolConformanceClaim) -> str:
    payload = {
        field.name: list(value) if isinstance(value, tuple) else value
        for field in fields(claim)
        for value in (getattr(claim, field.name),)
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _evidence_refs(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise PR196ProtocolConformanceError("claim field 'evidence_refs' must be a string list")
    refs = tuple(value)
    if not all(isinstance(item, str) and _EVIDENCE_REF.fullmatch(item) for item in refs):
        raise PR196ProtocolConformanceError(
            "claim field 'evidence_refs' must contain safe evidence paths"
        )
    return refs
