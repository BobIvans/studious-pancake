"""AGG-09 OPS-01: portfolio budgets, fenced recovery and trust recovery.

This module composes evidence emitted by the existing treasury, HA/DR and
credential authorities.  It is deliberately effect-free: it neither owns a
ledger nor loads secrets, signs, submits, promotes a release, or enables live
execution.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import re
from typing import Iterable

from src.ha_dr.mpr2616 import CoordinatorCapabilities, RestoreEvidence

SCHEMA_VERSION = "agg09.ops01.v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class Agg09Ops01Error(ValueError):
    """Malformed or contradictory OPS-01 evidence."""


def _nonnegative(value: int, name: str) -> None:
    if type(value) is not int or value < 0:
        raise Agg09Ops01Error(f"{name} must be a non-negative integer")


def _positive(value: int, name: str) -> None:
    if type(value) is not int or value <= 0:
        raise Agg09Ops01Error(f"{name} must be a positive integer")


def _sha(value: str, name: str) -> None:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise Agg09Ops01Error(f"{name} must be a lowercase sha256 digest")


def _digest(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class AssetRiskCap:
    asset_id: str
    max_total_risk_atoms: int
    protected_reserve_atoms: int

    def __post_init__(self) -> None:
        if not self.asset_id.strip():
            raise Agg09Ops01Error("asset_id is required")
        _nonnegative(self.max_total_risk_atoms, "max_total_risk_atoms")
        _nonnegative(self.protected_reserve_atoms, "protected_reserve_atoms")


@dataclass(frozen=True, slots=True)
class PortfolioExposure:
    """One durable treasury/risk snapshot row in exact asset units."""

    owner_id: str
    strategy_id: str
    chain_id: str
    asset_id: str
    owned_equity_atoms: int
    reserved_atoms: int
    unresolved_atoms: int
    worst_failure_atoms: int
    provider_spend_atoms: int
    collateral_atoms: int = 0
    loan_capacity_atoms: int = 0
    client_capital_atoms: int = 0

    def __post_init__(self) -> None:
        for name in ("owner_id", "strategy_id", "chain_id", "asset_id"):
            if not getattr(self, name).strip():
                raise Agg09Ops01Error(f"{name} is required")
        for name in (
            "owned_equity_atoms",
            "reserved_atoms",
            "unresolved_atoms",
            "worst_failure_atoms",
            "provider_spend_atoms",
            "collateral_atoms",
            "loan_capacity_atoms",
            "client_capital_atoms",
        ):
            _nonnegative(getattr(self, name), name)


@dataclass(frozen=True, slots=True)
class AssetBudgetDecision:
    asset_id: str
    owned_equity_atoms: int
    used_risk_atoms: int
    protected_reserve_atoms: int
    free_owned_atoms: int
    excluded_non_equity_atoms: int
    allowed: bool
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PortfolioBudgetState:
    decisions: tuple[AssetBudgetDecision, ...]
    allowed: bool
    reason_codes: tuple[str, ...]
    live_enabled: bool = False
    automatic_scale_up_allowed: bool = False

    @property
    def semantic_digest(self) -> str:
        return _digest(
            {
                "schema": SCHEMA_VERSION,
                "decisions": [asdict(item) for item in self.decisions],
                "allowed": self.allowed,
                "reason_codes": list(self.reason_codes),
                "live_enabled": self.live_enabled,
                "automatic_scale_up_allowed": self.automatic_scale_up_allowed,
            }
        )


def evaluate_portfolio_budget(
    exposures: Iterable[PortfolioExposure],
    caps: Iterable[AssetRiskCap],
) -> PortfolioBudgetState:
    """Evaluate one portfolio view without manufacturing equity.

    Collateral, lender capacity and client capital are explicitly excluded from
    owned equity.  Parallel strategy rows consume the same per-asset cap.
    """

    cap_by_asset: dict[str, AssetRiskCap] = {}
    for cap in caps:
        if cap.asset_id in cap_by_asset:
            raise Agg09Ops01Error(f"duplicate cap for asset {cap.asset_id}")
        cap_by_asset[cap.asset_id] = cap

    rows: dict[str, list[PortfolioExposure]] = {}
    for exposure in exposures:
        rows.setdefault(exposure.asset_id, []).append(exposure)

    decisions: list[AssetBudgetDecision] = []
    global_reasons: list[str] = []
    for asset_id in sorted(rows):
        items = rows[asset_id]
        cap = cap_by_asset.get(asset_id)
        reasons: list[str] = []
        if cap is None:
            reasons.append("AGG09_PORTFOLIO_CAP_MISSING")
            protected_reserve = 0
            max_risk = 0
        else:
            protected_reserve = cap.protected_reserve_atoms
            max_risk = cap.max_total_risk_atoms

        owner_equity: dict[str, int] = {}
        for item in items:
            prior = owner_equity.setdefault(item.owner_id, item.owned_equity_atoms)
            if prior != item.owned_equity_atoms:
                reasons.append("AGG09_PORTFOLIO_EQUITY_CONFLICT")

        owned = sum(owner_equity.values())
        used = sum(
            item.reserved_atoms
            + item.unresolved_atoms
            + item.worst_failure_atoms
            + item.provider_spend_atoms
            for item in items
        )
        excluded = sum(
            item.collateral_atoms + item.loan_capacity_atoms + item.client_capital_atoms
            for item in items
        )
        if any(item.client_capital_atoms for item in items):
            reasons.append("AGG09_CLIENT_CAPITAL_PRESENT_IN_OWNER_SCOPE")
        if used > max_risk:
            reasons.append("AGG09_PORTFOLIO_RISK_CAP_EXCEEDED")
        if used + protected_reserve > owned:
            reasons.append("AGG09_PORTFOLIO_OWNED_EQUITY_EXHAUSTED")
        free = max(0, owned - used - protected_reserve)
        decisions.append(
            AssetBudgetDecision(
                asset_id=asset_id,
                owned_equity_atoms=owned,
                used_risk_atoms=used,
                protected_reserve_atoms=protected_reserve,
                free_owned_atoms=free,
                excluded_non_equity_atoms=excluded,
                allowed=not reasons,
                reason_codes=tuple(sorted(set(reasons))),
            )
        )
        global_reasons.extend(reasons)

    missing_rows = sorted(set(cap_by_asset) - set(rows))
    if missing_rows:
        global_reasons.append("AGG09_PORTFOLIO_EXPOSURE_MISSING")
    if not rows:
        global_reasons.append("AGG09_PORTFOLIO_EMPTY")

    return PortfolioBudgetState(
        decisions=tuple(decisions),
        allowed=not global_reasons,
        reason_codes=tuple(sorted(set(global_reasons))),
    )


@dataclass(frozen=True, slots=True)
class RecoveryEvidence:
    restore: RestoreEvidence
    coordinator: CoordinatorCapabilities | None
    prior_fence_generation: int
    recovered_fence_generation: int
    reservations_preserved: bool
    unknown_dispatches_quarantined: bool
    revoked_credentials_preserved: bool
    chain_state_reconciled: bool
    signer_recovery_proven: bool

    def __post_init__(self) -> None:
        _nonnegative(self.prior_fence_generation, "prior_fence_generation")
        _positive(self.recovered_fence_generation, "recovered_fence_generation")
        for name in (
            "reservations_preserved",
            "unknown_dispatches_quarantined",
            "revoked_credentials_preserved",
            "chain_state_reconciled",
            "signer_recovery_proven",
        ):
            if type(getattr(self, name)) is not bool:
                raise Agg09Ops01Error(f"{name} must be boolean")


@dataclass(frozen=True, slots=True)
class RecoveryPromotion:
    restore_safe_default_off: bool
    production_failover_qualified: bool
    reason_codes: tuple[str, ...]
    rpo_seconds: int
    fence_advanced: bool
    live_enabled: bool = False
    resend_unknown_allowed: bool = False


def evaluate_recovery(evidence: RecoveryEvidence) -> RecoveryPromotion:
    reasons: list[str] = []
    if not evidence.restore.safe_for_takeover:
        reasons.append("AGG09_RESTORE_EVIDENCE_UNSAFE")
    if evidence.recovered_fence_generation <= evidence.prior_fence_generation:
        reasons.append("AGG09_FENCE_DID_NOT_ADVANCE")
    if not evidence.reservations_preserved:
        reasons.append("AGG09_RESERVATIONS_NOT_PRESERVED")
    if not evidence.unknown_dispatches_quarantined:
        reasons.append("AGG09_UNKNOWN_DISPATCH_NOT_QUARANTINED")
    if not evidence.revoked_credentials_preserved:
        reasons.append("AGG09_REVOKED_CREDENTIAL_RESURRECTED")
    if not evidence.chain_state_reconciled:
        reasons.append("AGG09_CHAIN_RECONCILIATION_MISSING")

    default_off_reasons = tuple(sorted(set(reasons)))
    restore_safe = not default_off_reasons
    production_reasons = list(default_off_reasons)
    coordinator_ok = (
        evidence.coordinator is not None and evidence.coordinator.production_eligible
    )
    if not coordinator_ok:
        production_reasons.append("AGG09_HA_COORDINATOR_NOT_PRODUCTION_QUALIFIED")
    if not evidence.signer_recovery_proven:
        production_reasons.append("AGG09_SIGNER_RECOVERY_NOT_PROVEN")

    return RecoveryPromotion(
        restore_safe_default_off=restore_safe,
        production_failover_qualified=not production_reasons,
        reason_codes=tuple(sorted(set(production_reasons))),
        rpo_seconds=evidence.restore.rpo_seconds,
        fence_advanced=evidence.recovered_fence_generation
        > evidence.prior_fence_generation,
        live_enabled=False,
        resend_unknown_allowed=False,
    )


@dataclass(frozen=True, slots=True)
class SecurityBoundaryEvidence:
    endpoint_allowlist_enforced: bool
    ssrf_private_targets_blocked: bool
    dns_rebinding_blocked: bool
    tls_policy_enforced: bool
    redirects_bounded: bool
    json_size_bounded: bool
    decompression_bounded: bool
    archive_traversal_blocked: bool
    filesystem_permissions_least_privilege: bool
    untrusted_metadata_non_executable: bool
    callpath_evidence_sha256: str

    def __post_init__(self) -> None:
        _sha(self.callpath_evidence_sha256, "callpath_evidence_sha256")


@dataclass(frozen=True, slots=True)
class SecurityHardeningReport:
    passed: bool
    reason_codes: tuple[str, ...]
    evidence_sha256: str


def evaluate_security_boundaries(
    evidence: SecurityBoundaryEvidence,
) -> SecurityHardeningReport:
    checks = {
        "AGG09_ENDPOINT_ALLOWLIST_MISSING": evidence.endpoint_allowlist_enforced,
        "AGG09_SSRF_PRIVATE_TARGET_NOT_BLOCKED": evidence.ssrf_private_targets_blocked,
        "AGG09_DNS_REBINDING_NOT_BLOCKED": evidence.dns_rebinding_blocked,
        "AGG09_TLS_POLICY_NOT_ENFORCED": evidence.tls_policy_enforced,
        "AGG09_REDIRECT_BOUND_MISSING": evidence.redirects_bounded,
        "AGG09_JSON_BOUND_MISSING": evidence.json_size_bounded,
        "AGG09_DECOMPRESSION_BOUND_MISSING": evidence.decompression_bounded,
        "AGG09_ARCHIVE_TRAVERSAL_NOT_BLOCKED": evidence.archive_traversal_blocked,
        "AGG09_FILESYSTEM_LEAST_PRIVILEGE_MISSING": (
            evidence.filesystem_permissions_least_privilege
        ),
        "AGG09_UNTRUSTED_METADATA_EXECUTABLE": (
            evidence.untrusted_metadata_non_executable
        ),
    }
    reasons = tuple(sorted(code for code, ok in checks.items() if not ok))
    return SecurityHardeningReport(
        passed=not reasons,
        reason_codes=reasons,
        evidence_sha256=_digest(asdict(evidence)),
    )


@dataclass(frozen=True, slots=True)
class CredentialRecoveryEvidence:
    secret_id: str
    active_version: str
    active_rotation_epoch: int
    active_revocation_epoch: int
    restored_rotation_epoch: int
    restored_revocation_epoch: int
    stale_handle_rejected: bool
    logs_redacted: bool
    rollback_resurrected_revoked_version: bool
    evidence_sha256: str

    def __post_init__(self) -> None:
        if not self.secret_id.strip() or not self.active_version.strip():
            raise Agg09Ops01Error("credential identity is required")
        for name in (
            "active_rotation_epoch",
            "active_revocation_epoch",
            "restored_rotation_epoch",
            "restored_revocation_epoch",
        ):
            _nonnegative(getattr(self, name), name)
        _sha(self.evidence_sha256, "evidence_sha256")


@dataclass(frozen=True, slots=True)
class RotationRecoveryReceipt:
    accepted: bool
    reason_codes: tuple[str, ...]
    live_enabled: bool = False


def evaluate_credential_recovery(
    evidence: CredentialRecoveryEvidence,
) -> RotationRecoveryReceipt:
    reasons: list[str] = []
    if evidence.restored_rotation_epoch < evidence.active_rotation_epoch:
        reasons.append("AGG09_ROTATION_EPOCH_ROLLED_BACK")
    if evidence.restored_revocation_epoch < evidence.active_revocation_epoch:
        reasons.append("AGG09_REVOCATION_EPOCH_ROLLED_BACK")
    if not evidence.stale_handle_rejected:
        reasons.append("AGG09_STALE_CREDENTIAL_HANDLE_ACCEPTED")
    if not evidence.logs_redacted:
        reasons.append("AGG09_CREDENTIAL_LOG_REDACTION_MISSING")
    if evidence.rollback_resurrected_revoked_version:
        reasons.append("AGG09_REVOKED_CREDENTIAL_RESURRECTED")
    return RotationRecoveryReceipt(
        accepted=not reasons,
        reason_codes=tuple(sorted(set(reasons))),
        live_enabled=False,
    )


__all__ = [
    "Agg09Ops01Error",
    "AssetBudgetDecision",
    "AssetRiskCap",
    "CredentialRecoveryEvidence",
    "PortfolioBudgetState",
    "PortfolioExposure",
    "RecoveryEvidence",
    "RecoveryPromotion",
    "RotationRecoveryReceipt",
    "SCHEMA_VERSION",
    "SecurityBoundaryEvidence",
    "SecurityHardeningReport",
    "evaluate_credential_recovery",
    "evaluate_portfolio_budget",
    "evaluate_recovery",
    "evaluate_security_boundaries",
]
