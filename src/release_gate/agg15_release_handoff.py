"""AGG-15 full-scope coverage audit and release-handoff contracts.

This module is deliberately not a promotion authority.  It consumes explicit
coverage/campaign/handoff evidence, checks that the current 352 planned NF
identities are represented without inflation, and produces a fail-closed handoff
report.  SUPER-08 extends this same owner rather than creating a second release
authority.
Canonical production promotion remains owned by MPR-2612.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Sequence

AGG15_SCHEMA_VERSION = "agg15.release-handoff.v2"
EXPECTED_NF_COUNT = 352
EXPECTED_NF_IDS = tuple(f"NF-{index:03d}" for index in range(1, EXPECTED_NF_COUNT + 1))

EXTENSION_SCOPE_ROWS = (
    *((f"NF-{index:03d}", "TREASURY-01", "PR-073") for index in range(329, 333)),
    *((f"NF-{index:03d}", "BATCH-01", "PR-074") for index in range(333, 337)),
    *((f"NF-{index:03d}", "UNIVERSE-01", "PR-075") for index in range(337, 341)),
    *((f"NF-{index:03d}", "ALT-01", "PR-076") for index in range(341, 345)),
    *((f"NF-{index:03d}", "FORMAT-01", "PR-077") for index in range(345, 349)),
    *((f"NF-{index:03d}", "FORMAT-02", "PR-078") for index in range(349, 353)),
)
EXTENSION_NF_OWNERS = {nf_id: owner for nf_id, owner, _ in EXTENSION_SCOPE_ROWS}
EXTENSION_SOURCE_PRS = {
    nf_id: source_pr for nf_id, _, source_pr in EXTENSION_SCOPE_ROWS
}
CANONICAL_PRODUCT_OWNER = "src.research.product"
CANONICAL_PRODUCT_ACCOUNTING_OWNER = "RevenueAttributionLedger"
EXPECTED_EVOLUTION_STAGES = (
    "record",
    "analyse",
    "hypothesis",
    "reviewed_change",
    "test",
    "qualification",
    "scoped_deploy",
)

_GIT_OBJECT_ID = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_NF_ID = re.compile(r"^NF-(?:00[1-9]|0[1-9][0-9]|[12][0-9]{2}|3[0-4][0-9]|35[0-2])$")
_AGG_ID = re.compile(r"^AGG-(?:0[1-9]|1[0-5])$")


class Agg15AuditError(ValueError):
    """Malformed or internally contradictory AGG-15 evidence."""


class ImplementationStatus(StrEnum):
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    IMPLEMENTED_OFFLINE = "IMPLEMENTED_OFFLINE"
    MERGED_CODE = "MERGED_CODE"
    BLOCKED = "BLOCKED"


class OperationalStatus(StrEnum):
    UNQUALIFIED = "UNQUALIFIED"
    EXTERNALLY_QUALIFIED_FOR_PROFILE = "EXTERNALLY_QUALIFIED_FOR_PROFILE"
    LIVE_ADMITTED_FOR_EXACT_SCOPE = "LIVE_ADMITTED_FOR_EXACT_SCOPE"
    EXPIRED = "EXPIRED"
    BLOCKED = "BLOCKED"


class ScopeDisposition(StrEnum):
    REQUIRED = "REQUIRED"
    RESEARCH = "RESEARCH"
    DEFERRED = "DEFERRED"
    REJECTED_WITH_EVIDENCE = "REJECTED_WITH_EVIDENCE"


@dataclass(frozen=True, slots=True)
class CoverageRecord:
    nf_id: str
    agg_id: str
    primary_owner: str
    contract_ref: str
    implementation_status: ImplementationStatus
    operational_status: OperationalStatus
    scope_disposition: ScopeDisposition
    test_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    blocker_codes: tuple[str, ...] = ()
    merge_commit: str | None = None

    def __post_init__(self) -> None:
        if not _NF_ID.fullmatch(self.nf_id):
            raise Agg15AuditError("AGG15_INVALID_NF_ID")
        if not _AGG_ID.fullmatch(self.agg_id):
            raise Agg15AuditError("AGG15_INVALID_AGG_ID")
        _text(self.primary_owner, "primary_owner")
        expected_extension_owner = EXTENSION_NF_OWNERS.get(self.nf_id)
        if (
            expected_extension_owner is not None
            and self.primary_owner != expected_extension_owner
        ):
            raise Agg15AuditError("AGG15_EXTENSION_OWNER_MISMATCH")
        _text(self.contract_ref, "contract_ref")
        _unique_texts(self.test_refs, "test_refs")
        _unique_texts(self.evidence_refs, "evidence_refs")
        _unique_texts(self.blocker_codes, "blocker_codes")
        if self.merge_commit is not None and not _GIT_OBJECT_ID.fullmatch(
            self.merge_commit
        ):
            raise Agg15AuditError("AGG15_INVALID_MERGE_COMMIT")
        implemented = self.implementation_status in {
            ImplementationStatus.IMPLEMENTED_OFFLINE,
            ImplementationStatus.MERGED_CODE,
        }
        if implemented and (not self.test_refs or not self.evidence_refs):
            raise Agg15AuditError("AGG15_IMPLEMENTATION_EVIDENCE_REQUIRED")
        if (
            self.implementation_status is ImplementationStatus.MERGED_CODE
            and self.merge_commit is None
        ):
            raise Agg15AuditError("AGG15_MERGED_CODE_COMMIT_REQUIRED")
        qualified = self.operational_status in {
            OperationalStatus.EXTERNALLY_QUALIFIED_FOR_PROFILE,
            OperationalStatus.LIVE_ADMITTED_FOR_EXACT_SCOPE,
        }
        if qualified and not self.evidence_refs:
            raise Agg15AuditError("AGG15_OPERATIONAL_EVIDENCE_REQUIRED")
        if (
            self.scope_disposition is ScopeDisposition.REJECTED_WITH_EVIDENCE
            and not self.evidence_refs
        ):
            raise Agg15AuditError("AGG15_REJECTION_EVIDENCE_REQUIRED")

    @property
    def evidence_completed(self) -> bool:
        return (
            self.implementation_status
            in {
                ImplementationStatus.IMPLEMENTED_OFFLINE,
                ImplementationStatus.MERGED_CODE,
            }
            and bool(self.test_refs)
            and bool(self.evidence_refs)
            and not self.blocker_codes
        )

    @property
    def required_complete(self) -> bool:
        if self.scope_disposition is not ScopeDisposition.REQUIRED:
            return True
        return self.evidence_completed and self.implementation_status is (
            ImplementationStatus.MERGED_CODE
        )


@dataclass(frozen=True, slots=True)
class CoverageAudit:
    mapped_nf_count: int
    evidence_completed_nf_count: int
    missing_nf_ids: tuple[str, ...]
    required_incomplete_nf_ids: tuple[str, ...]
    research_or_deferred_nf_ids: tuple[str, ...]
    coverage_digest: str

    @property
    def structurally_complete(self) -> bool:
        return self.mapped_nf_count == EXPECTED_NF_COUNT and not self.missing_nf_ids

    @property
    def full_target_code_complete(self) -> bool:
        return (
            self.structurally_complete
            and self.evidence_completed_nf_count == EXPECTED_NF_COUNT
            and not self.required_incomplete_nf_ids
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {
            "structurally_complete": self.structurally_complete,
            "full_target_code_complete": self.full_target_code_complete,
        }


@dataclass(frozen=True, slots=True)
class SelectedProfile:
    profile_id: str
    release_generation: str
    implementation_status: ImplementationStatus
    operational_status: OperationalStatus
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.profile_id, "profile_id")
        _text(self.release_generation, "release_generation")
        _unique_texts(self.evidence_refs, "evidence_refs")

    @property
    def externally_qualified(self) -> bool:
        return (
            self.implementation_status is ImplementationStatus.MERGED_CODE
            and self.operational_status
            is OperationalStatus.EXTERNALLY_QUALIFIED_FOR_PROFILE
            and bool(self.evidence_refs)
        )


@dataclass(frozen=True, slots=True)
class CampaignEvidence:
    kind: str
    generation: str
    ref: str

    def __post_init__(self) -> None:
        _text(self.kind, "kind")
        _text(self.generation, "generation")
        _text(self.ref, "ref")


@dataclass(frozen=True, slots=True)
class IntegratedCampaign:
    release_generation: str
    lifecycle_owner: str
    capital_owner: str
    release_owner: str
    evidence: tuple[CampaignEvidence, ...]
    stress_unknown_outcomes_checked: bool
    shared_capacity_conflicts_checked: bool
    live_enabled: bool = False
    automatic_scale_up_allowed: bool = False

    def __post_init__(self) -> None:
        _text(self.release_generation, "release_generation")
        _text(self.lifecycle_owner, "lifecycle_owner")
        _text(self.capital_owner, "capital_owner")
        _text(self.release_owner, "release_owner")
        if self.live_enabled:
            raise Agg15AuditError("AGG15_LIVE_DEFAULT_FORBIDDEN")
        if self.automatic_scale_up_allowed:
            raise Agg15AuditError("AGG15_AUTO_SCALE_FORBIDDEN")

    @property
    def blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if not self.evidence:
            blockers.append("AGG15_INTEGRATED_CAMPAIGN_EVIDENCE_MISSING")
        if any(item.generation != self.release_generation for item in self.evidence):
            blockers.append("AGG15_CAMPAIGN_GENERATION_MIX")
        if not self.stress_unknown_outcomes_checked:
            blockers.append("AGG15_UNKNOWN_OUTCOME_STRESS_MISSING")
        if not self.shared_capacity_conflicts_checked:
            blockers.append("AGG15_SHARED_CAPACITY_STRESS_MISSING")
        return tuple(blockers)


@dataclass(frozen=True, slots=True)
class OperatorHandoff:
    bootstrap_commands: tuple[str, ...]
    status_commands: tuple[str, ...]
    stop_commands: tuple[str, ...]
    recovery_commands: tuple[str, ...]
    remaining_scopes: tuple[str, ...]
    secrets_embedded: bool
    live_default: bool

    def __post_init__(self) -> None:
        for name in (
            "bootstrap_commands",
            "status_commands",
            "stop_commands",
            "recovery_commands",
        ):
            _unique_texts(getattr(self, name), name)
        _unique_texts(self.remaining_scopes, "remaining_scopes")
        if self.secrets_embedded:
            raise Agg15AuditError("AGG15_HANDOFF_CONTAINS_SECRETS")
        if self.live_default:
            raise Agg15AuditError("AGG15_HANDOFF_LIVE_DEFAULT_FORBIDDEN")

    @property
    def ready(self) -> bool:
        return all(
            (
                self.bootstrap_commands,
                self.status_commands,
                self.stop_commands,
                self.recovery_commands,
            )
        )


@dataclass(frozen=True, slots=True)
class ContinuousEvolution:
    stages: tuple[str, ...]
    independent_promotion_required: bool
    risk_authority_overridable: bool
    auto_live: bool

    def __post_init__(self) -> None:
        _unique_texts(self.stages, "stages")
        if self.auto_live:
            raise Agg15AuditError("AGG15_EVOLUTION_AUTO_LIVE_FORBIDDEN")
        if self.risk_authority_overridable:
            raise Agg15AuditError("AGG15_RISK_AUTHORITY_OVERRIDE_FORBIDDEN")

    @property
    def ready(self) -> bool:
        return (
            self.stages == EXPECTED_EVOLUTION_STAGES
            and self.independent_promotion_required
            and not self.risk_authority_overridable
            and not self.auto_live
        )


@dataclass(frozen=True, slots=True)
class ProductBoundary:
    """Evidence that PRODUCT-01 cannot inflate trading PnL or execution authority."""

    product_owner: str
    accounting_owner: str
    evidence_refs: tuple[str, ...]
    service_accounting_separate: bool
    product_revenue_is_trading_pnl: bool = False
    client_funds_are_trading_capital: bool = False
    signing_allowed: bool = False
    submission_allowed: bool = False
    remote_product_mutation_performed: bool = False

    def __post_init__(self) -> None:
        _text(self.product_owner, "product_owner")
        _text(self.accounting_owner, "accounting_owner")
        _unique_texts(self.evidence_refs, "product_evidence_refs")
        if self.product_revenue_is_trading_pnl:
            raise Agg15AuditError("AGG15_PRODUCT_REVENUE_AS_TRADING_PNL_FORBIDDEN")
        if self.client_funds_are_trading_capital:
            raise Agg15AuditError("AGG15_CLIENT_FUNDS_AS_TRADING_CAPITAL_FORBIDDEN")
        if self.signing_allowed or self.submission_allowed:
            raise Agg15AuditError("AGG15_PRODUCT_EXECUTION_AUTHORITY_FORBIDDEN")
        if self.remote_product_mutation_performed:
            raise Agg15AuditError("AGG15_PRODUCT_REMOTE_MUTATION_FORBIDDEN")

    @property
    def ready(self) -> bool:
        return (
            self.product_owner == CANONICAL_PRODUCT_OWNER
            and self.accounting_owner == CANONICAL_PRODUCT_ACCOUNTING_OWNER
            and self.service_accounting_separate
            and bool(self.evidence_refs)
        )


@dataclass(frozen=True, slots=True)
class ReleaseHandoffReport:
    schema_version: str
    release_id: str
    source_commit: str
    coverage: CoverageAudit
    selected_profiles: tuple[SelectedProfile, ...]
    product_boundary_ready: bool
    blockers: tuple[str, ...]
    scoped_release_handoff_ready: bool
    full_target_handoff_ready: bool
    eligible_for_canonical_release_review: bool
    production_ready: bool = False
    release_claim_allowed: bool = False
    live_enabled: bool = False
    automatic_scale_up_allowed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "release_id": self.release_id,
            "source_commit": self.source_commit,
            "coverage": self.coverage.to_dict(),
            "selected_profiles": [asdict(item) for item in self.selected_profiles],
            "product_boundary_ready": self.product_boundary_ready,
            "blockers": list(self.blockers),
            "scoped_release_handoff_ready": self.scoped_release_handoff_ready,
            "full_target_handoff_ready": self.full_target_handoff_ready,
            "eligible_for_canonical_release_review": (
                self.eligible_for_canonical_release_review
            ),
            "production_ready": self.production_ready,
            "release_claim_allowed": self.release_claim_allowed,
            "live_enabled": self.live_enabled,
            "automatic_scale_up_allowed": self.automatic_scale_up_allowed,
        }


def audit_coverage(records: Iterable[CoverageRecord]) -> CoverageAudit:
    rows = tuple(records)
    by_id: dict[str, CoverageRecord] = {}
    for row in rows:
        if row.nf_id in by_id:
            raise Agg15AuditError("AGG15_DUPLICATE_NF_ID")
        by_id[row.nf_id] = row
    missing = tuple(item for item in EXPECTED_NF_IDS if item not in by_id)
    unexpected = tuple(sorted(set(by_id).difference(EXPECTED_NF_IDS)))
    if unexpected:
        raise Agg15AuditError("AGG15_UNEXPECTED_NF_ID")
    required_incomplete = tuple(
        row.nf_id
        for row in rows
        if row.scope_disposition is ScopeDisposition.REQUIRED
        and not row.required_complete
    )
    research = tuple(
        row.nf_id
        for row in rows
        if row.scope_disposition
        in {
            ScopeDisposition.RESEARCH,
            ScopeDisposition.DEFERRED,
            ScopeDisposition.REJECTED_WITH_EVIDENCE,
        }
    )
    payload = [
        {
            "nf_id": row.nf_id,
            "agg_id": row.agg_id,
            "primary_owner": row.primary_owner,
            "contract_ref": row.contract_ref,
            "implementation_status": row.implementation_status.value,
            "operational_status": row.operational_status.value,
            "scope_disposition": row.scope_disposition.value,
            "test_refs": list(row.test_refs),
            "evidence_refs": list(row.evidence_refs),
            "blocker_codes": list(row.blocker_codes),
            "merge_commit": row.merge_commit,
        }
        for row in sorted(rows, key=lambda item: item.nf_id)
    ]
    digest = hashlib.sha256(_canonical_json(payload).encode()).hexdigest()
    return CoverageAudit(
        mapped_nf_count=len(by_id),
        evidence_completed_nf_count=sum(row.evidence_completed for row in rows),
        missing_nf_ids=missing,
        required_incomplete_nf_ids=required_incomplete,
        research_or_deferred_nf_ids=research,
        coverage_digest=digest,
    )


def evaluate_release_handoff(payload: Mapping[str, Any]) -> ReleaseHandoffReport:
    if payload.get("schema_version") != AGG15_SCHEMA_VERSION:
        raise Agg15AuditError("AGG15_SCHEMA_MISMATCH")
    release_id = _text(payload.get("release_id"), "release_id")
    source_commit = _text(payload.get("source_commit"), "source_commit")
    if not _GIT_OBJECT_ID.fullmatch(source_commit):
        raise Agg15AuditError("AGG15_SOURCE_COMMIT_INVALID")
    if _bool_field(payload, "live_enabled", default=False):
        raise Agg15AuditError("AGG15_LIVE_DEFAULT_FORBIDDEN")
    if _bool_field(payload, "automatic_scale_up_allowed", default=False):
        raise Agg15AuditError("AGG15_AUTO_SCALE_FORBIDDEN")

    records = tuple(_coverage_record(item) for item in _list(payload, "coverage"))
    coverage = audit_coverage(records)
    profiles = tuple(_profile(item) for item in _list(payload, "selected_profiles"))
    campaign_raw = payload.get("integrated_campaign")
    campaign = _campaign(campaign_raw) if isinstance(campaign_raw, Mapping) else None
    handoff_raw = payload.get("operator_handoff")
    handoff = _handoff(handoff_raw) if isinstance(handoff_raw, Mapping) else None
    evolution_raw = payload.get("continuous_evolution")
    evolution = (
        _evolution(evolution_raw) if isinstance(evolution_raw, Mapping) else None
    )
    product_raw = payload.get("product_boundary")
    product_boundary = (
        _product_boundary(product_raw) if isinstance(product_raw, Mapping) else None
    )

    blockers: list[str] = []
    blockers.extend(code for row in records for code in row.blocker_codes)
    if not coverage.structurally_complete:
        blockers.append("AGG15_COVERAGE_NOT_352")
    if coverage.required_incomplete_nf_ids:
        blockers.append("AGG15_REQUIRED_SCOPE_INCOMPLETE")
    if not profiles:
        blockers.append("AGG15_SELECTED_PROFILE_REQUIRED")
    if any(not profile.externally_qualified for profile in profiles):
        blockers.append("AGG15_SELECTED_PROFILE_UNQUALIFIED")
    profile_generation_match = campaign is not None and all(
        profile.release_generation == campaign.release_generation
        for profile in profiles
    )
    if campaign is None:
        blockers.append("AGG15_INTEGRATED_CAMPAIGN_MISSING")
    else:
        blockers.extend(campaign.blockers)
        if profiles and not profile_generation_match:
            blockers.append("AGG15_PROFILE_GENERATION_MIX")
    if handoff is None or not handoff.ready:
        blockers.append("AGG15_OPERATOR_HANDOFF_INCOMPLETE")
    if evolution is None or not evolution.ready:
        blockers.append("AGG15_CONTINUOUS_EVOLUTION_INCOMPLETE")
    if product_boundary is None:
        blockers.append("AGG15_PRODUCT_BOUNDARY_MISSING")
    elif not product_boundary.ready:
        blockers.append("AGG15_PRODUCT_BOUNDARY_INCOMPLETE")

    receipt = payload.get("release_authority_receipt_ref")
    canonical_release_receipt_present = isinstance(receipt, str) and bool(
        receipt.strip()
    )
    scoped_ready = (
        coverage.structurally_complete
        and bool(profiles)
        and all(profile.externally_qualified for profile in profiles)
        and campaign is not None
        and not campaign.blockers
        and profile_generation_match
        and handoff is not None
        and handoff.ready
        and evolution is not None
        and evolution.ready
        and product_boundary is not None
        and product_boundary.ready
    )
    full_ready = scoped_ready and coverage.full_target_code_complete
    review_ready = scoped_ready and canonical_release_receipt_present and not blockers
    if scoped_ready and not canonical_release_receipt_present:
        blockers.append("AGG15_CANONICAL_RELEASE_RECEIPT_REQUIRED")

    return ReleaseHandoffReport(
        schema_version=AGG15_SCHEMA_VERSION,
        release_id=release_id,
        source_commit=source_commit,
        coverage=coverage,
        selected_profiles=profiles,
        product_boundary_ready=(
            product_boundary is not None and product_boundary.ready
        ),
        blockers=tuple(dict.fromkeys(blockers)),
        scoped_release_handoff_ready=scoped_ready,
        full_target_handoff_ready=full_ready,
        eligible_for_canonical_release_review=review_ready,
    )


def evaluate_release_handoff_file(path: str | Path) -> ReleaseHandoffReport:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise Agg15AuditError("AGG15_MANIFEST_OBJECT_REQUIRED")
    return evaluate_release_handoff(payload)


def _coverage_record(raw: Any) -> CoverageRecord:
    if not isinstance(raw, Mapping):
        raise Agg15AuditError("AGG15_COVERAGE_ROW_OBJECT_REQUIRED")
    merge_commit = raw.get("merge_commit")
    return CoverageRecord(
        nf_id=_text(raw.get("nf_id"), "nf_id"),
        agg_id=_text(raw.get("agg_id"), "agg_id"),
        primary_owner=_text(raw.get("primary_owner"), "primary_owner"),
        contract_ref=_text(raw.get("contract_ref"), "contract_ref"),
        implementation_status=ImplementationStatus(
            _text(raw.get("implementation_status"), "implementation_status")
        ),
        operational_status=OperationalStatus(
            _text(raw.get("operational_status"), "operational_status")
        ),
        scope_disposition=ScopeDisposition(
            _text(raw.get("scope_disposition"), "scope_disposition")
        ),
        test_refs=_texts(raw.get("test_refs", ()), "test_refs"),
        evidence_refs=_texts(raw.get("evidence_refs", ()), "evidence_refs"),
        blocker_codes=_texts(raw.get("blocker_codes", ()), "blocker_codes"),
        merge_commit=(
            _text(merge_commit, "merge_commit") if merge_commit is not None else None
        ),
    )


def _profile(raw: Any) -> SelectedProfile:
    if not isinstance(raw, Mapping):
        raise Agg15AuditError("AGG15_PROFILE_OBJECT_REQUIRED")
    return SelectedProfile(
        profile_id=_text(raw.get("profile_id"), "profile_id"),
        release_generation=_text(raw.get("release_generation"), "release_generation"),
        implementation_status=ImplementationStatus(
            _text(raw.get("implementation_status"), "implementation_status")
        ),
        operational_status=OperationalStatus(
            _text(raw.get("operational_status"), "operational_status")
        ),
        evidence_refs=_texts(raw.get("evidence_refs", ()), "evidence_refs"),
    )


def _campaign(raw: Mapping[str, Any]) -> IntegratedCampaign:
    evidence_raw = _list(raw, "evidence")
    evidence = tuple(
        CampaignEvidence(
            kind=_text(item.get("kind"), "kind"),
            generation=_text(item.get("generation"), "generation"),
            ref=_text(item.get("ref"), "ref"),
        )
        for item in evidence_raw
        if isinstance(item, Mapping)
    )
    if len(evidence) != len(evidence_raw):
        raise Agg15AuditError("AGG15_CAMPAIGN_EVIDENCE_OBJECT_REQUIRED")
    return IntegratedCampaign(
        release_generation=_text(raw.get("release_generation"), "release_generation"),
        lifecycle_owner=_text(raw.get("lifecycle_owner"), "lifecycle_owner"),
        capital_owner=_text(raw.get("capital_owner"), "capital_owner"),
        release_owner=_text(raw.get("release_owner"), "release_owner"),
        evidence=evidence,
        stress_unknown_outcomes_checked=_bool_field(
            raw, "stress_unknown_outcomes_checked", default=False
        ),
        shared_capacity_conflicts_checked=_bool_field(
            raw, "shared_capacity_conflicts_checked", default=False
        ),
        live_enabled=_bool_field(raw, "live_enabled", default=False),
        automatic_scale_up_allowed=_bool_field(
            raw, "automatic_scale_up_allowed", default=False
        ),
    )


def _handoff(raw: Mapping[str, Any]) -> OperatorHandoff:
    return OperatorHandoff(
        bootstrap_commands=_texts(
            raw.get("bootstrap_commands", ()), "bootstrap_commands"
        ),
        status_commands=_texts(raw.get("status_commands", ()), "status_commands"),
        stop_commands=_texts(raw.get("stop_commands", ()), "stop_commands"),
        recovery_commands=_texts(raw.get("recovery_commands", ()), "recovery_commands"),
        remaining_scopes=_texts(raw.get("remaining_scopes", ()), "remaining_scopes"),
        secrets_embedded=_bool_field(raw, "secrets_embedded", default=False),
        live_default=_bool_field(raw, "live_default", default=False),
    )


def _evolution(raw: Mapping[str, Any]) -> ContinuousEvolution:
    return ContinuousEvolution(
        stages=_texts(raw.get("stages", ()), "stages"),
        independent_promotion_required=_bool_field(
            raw, "independent_promotion_required", default=False
        ),
        risk_authority_overridable=_bool_field(
            raw, "risk_authority_overridable", default=False
        ),
        auto_live=_bool_field(raw, "auto_live", default=False),
    )


def _product_boundary(raw: Mapping[str, Any]) -> ProductBoundary:
    return ProductBoundary(
        product_owner=_text(raw.get("product_owner"), "product_owner"),
        accounting_owner=_text(raw.get("accounting_owner"), "accounting_owner"),
        evidence_refs=_texts(raw.get("evidence_refs", ()), "product_evidence_refs"),
        service_accounting_separate=_bool_field(
            raw, "service_accounting_separate", default=False
        ),
        product_revenue_is_trading_pnl=_bool_field(
            raw, "product_revenue_is_trading_pnl", default=False
        ),
        client_funds_are_trading_capital=_bool_field(
            raw, "client_funds_are_trading_capital", default=False
        ),
        signing_allowed=_bool_field(raw, "signing_allowed", default=False),
        submission_allowed=_bool_field(raw, "submission_allowed", default=False),
        remote_product_mutation_performed=_bool_field(
            raw, "remote_product_mutation_performed", default=False
        ),
    )


def _list(raw: Mapping[str, Any], key: str) -> Sequence[Any]:
    value = raw.get(key)
    if not isinstance(value, list):
        raise Agg15AuditError(f"AGG15_{key.upper()}_LIST_REQUIRED")
    return value


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise Agg15AuditError(f"AGG15_{name.upper()}_REQUIRED")
    return value.strip()


def _texts(value: Any, name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise Agg15AuditError(f"AGG15_{name.upper()}_LIST_REQUIRED")
    result = tuple(_text(item, name) for item in value)
    _unique_texts(result, name)
    return result


def _unique_texts(values: Sequence[str], name: str) -> None:
    if len(set(values)) != len(values):
        raise Agg15AuditError(f"AGG15_{name.upper()}_DUPLICATE")


def _bool_field(
    raw: Mapping[str, Any],
    key: str,
    *,
    default: bool,
) -> bool:
    if key not in raw:
        return default
    value = raw[key]
    if type(value) is not bool:
        raise Agg15AuditError(f"AGG15_{key.upper()}_BOOLEAN_REQUIRED")
    return value


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


__all__ = [
    "AGG15_SCHEMA_VERSION",
    "EXPECTED_EVOLUTION_STAGES",
    "EXPECTED_NF_COUNT",
    "EXPECTED_NF_IDS",
    "Agg15AuditError",
    "CampaignEvidence",
    "ContinuousEvolution",
    "CoverageAudit",
    "CoverageRecord",
    "ImplementationStatus",
    "IntegratedCampaign",
    "OperationalStatus",
    "OperatorHandoff",
    "ReleaseHandoffReport",
    "ScopeDisposition",
    "SelectedProfile",
    "audit_coverage",
    "evaluate_release_handoff",
    "evaluate_release_handoff_file",
]
