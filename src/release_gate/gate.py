"""Fail-closed production release gate for roadmap PR-047."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Callable, Iterable

from .models import (
    DrillKind,
    EvidenceKind,
    FilePin,
    FindingDisposition,
    OwnershipKind,
    ReleaseManifest,
    SignoffRole,
    VerificationKind,
)

_REQUIRED_EVIDENCE = frozenset(EvidenceKind)
_REQUIRED_DRILLS = frozenset(DrillKind)
_REQUIRED_OWNERSHIP = frozenset(OwnershipKind)
_REQUIRED_SIGNOFFS = frozenset(SignoffRole)


@dataclass(frozen=True, slots=True)
class ReleaseGateResult:
    schema_version: str
    release_id: str
    production_ready: bool
    state: str
    manifest_sha256: str
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    checks_evaluated: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class ReleaseGate:
    """Evaluate evidence without enabling or invoking any execution path."""

    def __init__(
        self,
        *,
        repo_root: str | Path,
        observed_code_commit: str | None = None,
        observed_contract_drift_ok: bool | None = None,
        evaluated_at: datetime | None = None,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.observed_code_commit = observed_code_commit
        self.observed_contract_drift_ok = observed_contract_drift_ok
        self.evaluated_at = evaluated_at or datetime.now(timezone.utc)
        if self.evaluated_at.tzinfo is None or self.evaluated_at.utcoffset() is None:
            raise ValueError("evaluated_at must be timezone-aware")

    def evaluate(self, manifest: ReleaseManifest) -> ReleaseGateResult:
        blockers: list[str] = []
        warnings: list[str] = []
        checks = 0

        def check(condition: bool, reason: str) -> None:
            nonlocal checks
            checks += 1
            if not condition:
                blockers.append(reason)

        check(
            manifest.expected_manifest_sha256 == manifest.manifest_sha256,
            "MANIFEST_HASH_MISMATCH",
        )
        check(
            self.observed_code_commit is not None,
            "OBSERVED_CODE_COMMIT_UNAVAILABLE",
        )
        if self.observed_code_commit is not None:
            check(
                self.observed_code_commit == manifest.artifacts.code_commit,
                "CODE_COMMIT_PIN_MISMATCH",
            )

        all_pins = self._all_pins(manifest)
        for pin in all_pins:
            check(self._pin_matches(pin), f"PIN_MISSING_OR_MISMATCH:{pin.path}")

        evidence_by_kind = {item.kind: item for item in manifest.evidence}
        check(
            set(evidence_by_kind) == set(_REQUIRED_EVIDENCE),
            "REQUIRED_PR039_PR046_EVIDENCE_MISSING",
        )
        for evidence_kind in sorted(_REQUIRED_EVIDENCE, key=str):
            evidence = evidence_by_kind.get(evidence_kind)
            if evidence is None:
                continue
            check(evidence.passed, f"EVIDENCE_NOT_PASSED:{evidence_kind.value}")
            check(
                evidence.human_reviewed,
                f"EVIDENCE_NOT_HUMAN_REVIEWED:{evidence_kind.value}",
            )

        self._check_findings(manifest.findings, check, warnings)

        drills_by_kind = {item.kind: item for item in manifest.drills}
        check(set(drills_by_kind) == set(_REQUIRED_DRILLS), "REQUIRED_DRILLS_MISSING")
        for drill_kind in sorted(_REQUIRED_DRILLS, key=str):
            drill = drills_by_kind.get(drill_kind)
            if drill is None:
                continue
            check(drill.passed, f"DRILL_FAILED:{drill_kind.value}")
            check(
                not drill.simulated,
                f"DRILL_NOT_ACTUALLY_REHEARSED:{drill_kind.value}",
            )

        wallet = manifest.wallet
        check(wallet.ownership_verified, "WALLET_OWNERSHIP_NOT_VERIFIED")
        check(wallet.signer_reference_verified, "SIGNER_REFERENCE_NOT_VERIFIED")
        check(
            wallet.observed_balance_lamports
            >= wallet.protected_reserve_lamports + wallet.fee_buffer_lamports,
            "WALLET_BALANCE_BELOW_RESERVE_AND_FEE_BUFFER",
        )

        ownership_by_kind = {item.kind: item for item in manifest.ownership_checks}
        check(
            set(ownership_by_kind) == set(_REQUIRED_OWNERSHIP),
            "RPC_PROVIDER_JITO_OWNERSHIP_CHECKS_MISSING",
        )
        for ownership_kind in sorted(_REQUIRED_OWNERSHIP, key=str):
            item = ownership_by_kind.get(ownership_kind)
            if item is None:
                continue
            check(
                item.ownership_verified,
                f"ACCOUNT_OWNERSHIP_NOT_VERIFIED:{ownership_kind.value}",
            )
            check(
                item.credential_rotation_owner_verified,
                f"CREDENTIAL_ROTATION_OWNER_NOT_VERIFIED:{ownership_kind.value}",
            )

        drift = manifest.external_contract_drift
        check(drift.ok, "MANIFEST_EXTERNAL_CONTRACT_DRIFT_NOT_OK")
        check(drift.diagnostic == "verified", "MANIFEST_DRIFT_DIAGNOSTIC_NOT_VERIFIED")
        check(
            self.observed_contract_drift_ok is True,
            "CURRENT_EXTERNAL_CONTRACT_DRIFT_REVALIDATION_FAILED",
        )

        check(manifest.rollout.manual_promotion_required, "MANUAL_PROMOTION_DISABLED")
        check(
            manifest.rollout.post_release_monitoring_seconds >= 24 * 60 * 60,
            "POST_RELEASE_MONITORING_WINDOW_TOO_SHORT",
        )

        signoffs_by_role = {item.role: item for item in manifest.signoffs}
        check(
            set(signoffs_by_role) == set(_REQUIRED_SIGNOFFS),
            "REQUIRED_SIGNOFFS_MISSING",
        )
        for signoff_role in sorted(_REQUIRED_SIGNOFFS, key=str):
            signoff = signoffs_by_role.get(signoff_role)
            if signoff is not None:
                check(
                    signoff.decision == "approve",
                    f"SIGNOFF_BLOCKED:{signoff_role.value}",
                )

        verification_kinds = {
            item.kind for item in manifest.verifications if item.status == "passed"
        }
        check(
            all(item.status == "passed" for item in manifest.verifications),
            "FAILED_VERIFICATION_PRESENT",
        )
        check(
            VerificationKind.REPOSITORY_CI in verification_kinds,
            "GREEN_REPOSITORY_CI_MISSING",
        )
        check(
            any(
                kind is not VerificationKind.REPOSITORY_CI
                for kind in verification_kinds
            ),
            "SINGLE_GREEN_CI_IS_NOT_RELEASE_EVIDENCE",
        )
        check(
            VerificationKind.OPERATIONAL_REHEARSAL in verification_kinds,
            "OPERATIONAL_REHEARSAL_VERIFICATION_MISSING",
        )
        check(
            VerificationKind.ARTIFACT_REBUILD in verification_kinds,
            "REPRODUCIBLE_ARTIFACT_REBUILD_MISSING",
        )
        check(
            VerificationKind.SBOM_BUILD in verification_kinds,
            "SBOM_BUILD_VERIFICATION_MISSING",
        )
        check(
            VerificationKind.SECURITY_GATE in verification_kinds,
            "SECURITY_GATE_VERIFICATION_MISSING",
        )

        unique_blockers = tuple(dict.fromkeys(blockers))
        production_ready = not unique_blockers
        return ReleaseGateResult(
            schema_version="pr047.release-gate-result.v1",
            release_id=manifest.release_id,
            production_ready=production_ready,
            state="production-ready" if production_ready else "blocked",
            manifest_sha256=manifest.manifest_sha256,
            blockers=unique_blockers,
            warnings=tuple(dict.fromkeys(warnings)),
            checks_evaluated=checks,
        )

    def _check_findings(
        self,
        findings: Iterable[FindingDisposition],
        check: Callable[[bool, str], None],
        warnings: list[str],
    ) -> None:
        for finding in findings:
            if finding.severity not in {"P0", "P1"}:
                continue
            if finding.disposition == "open":
                check(False, f"OPEN_{finding.severity}_FINDING:{finding.finding_id}")
            elif finding.disposition == "accepted":
                check(
                    finding.accepted_until is not None
                    and finding.accepted_until > self.evaluated_at,
                    f"RISK_ACCEPTANCE_EXPIRED:{finding.finding_id}",
                )
                warnings.append(
                    "DOCUMENTED_RISK_ACCEPTANCE:"
                    f"{finding.finding_id}:{finding.risk_owner}"
                )

    def _pin_matches(self, pin: FilePin) -> bool:
        candidate = (self.repo_root / pin.path).resolve()
        try:
            candidate.relative_to(self.repo_root)
        except ValueError:
            return False
        if not candidate.is_file():
            return False
        observed = hashlib.sha256(candidate.read_bytes()).hexdigest()
        return observed == pin.sha256

    @staticmethod
    def _all_pins(manifest: ReleaseManifest) -> tuple[FilePin, ...]:
        pins: list[FilePin] = [
            *manifest.artifacts.config_pins,
            *manifest.artifacts.contract_pins,
            manifest.artifacts.sbom_pin,
            *(item.pin for item in manifest.evidence),
            *(item.evidence_pin for item in manifest.drills),
            manifest.external_contract_drift.report_pin,
            manifest.rollout.rollback_runbook_pin,
        ]
        pins.extend(
            item.evidence_pin
            for item in manifest.verifications
            if item.evidence_pin is not None
        )
        return tuple(pins)
