from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.release_gate import (
    AccountOwnershipCheck,
    DrillKind,
    DrillRecord,
    EvidenceKind,
    EvidenceReference,
    ExternalContractDriftEvidence,
    FilePin,
    FindingDisposition,
    OwnershipKind,
    PinKind,
    ReleaseArtifacts,
    ReleaseGate,
    ReleaseManifest,
    RolloutPlan,
    RolloutStage,
    Signoff,
    SignoffRole,
    VerificationKind,
    VerificationRecord,
    WalletFundingCheck,
)

NOW = datetime(2026, 7, 20, 20, 0, tzinfo=timezone.utc)
COMMIT = "a" * 40
WALLET = "J5CBzXpcYn6WR2JBah8zU4Yxct985CAFGwXRcFaX2pbS"


def _write(root: Path, path: str, content: str) -> FilePin:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    kind = PinKind.EVIDENCE
    if path.startswith("config/"):
        kind = PinKind.CONFIG
    elif path.startswith("contracts/"):
        kind = PinKind.CONTRACT
    elif path.endswith("sbom.json"):
        kind = PinKind.SBOM
    elif path.startswith("drills/"):
        kind = PinKind.DRILL
    elif path.startswith("runbooks/"):
        kind = PinKind.RUNBOOK
    return FilePin(path=path, sha256=digest, kind=kind)


def _manifest(root: Path, **changes: object) -> ReleaseManifest:
    config_pin = _write(root, "config/runtime.json", "{}\n")
    contract_pin = _write(root, "contracts/external.json", "{}\n")
    sbom_pin = _write(root, "artifacts/sbom.json", "{}\n")
    pr039_pin = _write(root, "evidence/pr039.json", '{"passed":true}\n')
    pr046_pin = _write(root, "evidence/pr046.json", '{"passed":true}\n')
    drift_pin = _write(root, "evidence/drift.json", '{"ok":true}\n')
    rollback_pin = _write(root, "runbooks/rollback.md", "rollback\n")

    drills = tuple(
        DrillRecord(
            kind=kind,
            performed_at=NOW,
            operator="operator@example.com",
            environment="mainnet-canary-account",
            passed=True,
            simulated=False,
            evidence_pin=_write(root, f"drills/{kind.value}.json", '{"passed":true}\n'),
        )
        for kind in DrillKind
    )
    evidence = (
        EvidenceReference(
            kind=EvidenceKind.PR039_SHADOW_SOAK,
            schema_version="pr039.shadow-soak-evidence.v1",
            pin=pr039_pin,
            passed=True,
            human_reviewed=True,
            reviewer="risk@example.com",
            reviewed_at=NOW,
        ),
        EvidenceReference(
            kind=EvidenceKind.PR046_LIMITED_LIVE_CANARY,
            schema_version="pr046.limited-live-canary.v1",
            pin=pr046_pin,
            passed=True,
            human_reviewed=True,
            reviewer="release@example.com",
            reviewed_at=NOW,
        ),
    )
    ownership = tuple(
        AccountOwnershipCheck(
            kind=kind,
            account_reference=f"{kind.value}-account-id",
            owner="operations@example.com",
            billing_owner="finance@example.com",
            credential_reference=f"env:{kind.value.upper()}_CREDENTIAL",
            ownership_verified=True,
            credential_rotation_owner_verified=True,
            checked_at=NOW,
            checker="security@example.com",
        )
        for kind in OwnershipKind
    )
    signoffs = tuple(
        Signoff(
            role=role,
            identity=f"{role.value}@example.com",
            decision="approve",
            signed_at=NOW,
        )
        for role in SignoffRole
    )
    verifications = tuple(
        VerificationRecord(
            kind=kind,
            identifier=f"verified-{kind.value}",
            status="passed",
            observed_at=NOW,
        )
        for kind in (
            VerificationKind.REPOSITORY_CI,
            VerificationKind.ARTIFACT_REBUILD,
            VerificationKind.SBOM_BUILD,
            VerificationKind.EXTERNAL_CONTRACT_DRIFT,
            VerificationKind.OPERATIONAL_REHEARSAL,
            VerificationKind.SECURITY_GATE,
        )
    )

    payload: dict[str, object] = {
        "release_id": "release-2026-07-20-canary-1",
        "generated_at": NOW,
        "expected_manifest_sha256": "0" * 64,
        "artifacts": ReleaseArtifacts(
            code_commit=COMMIT,
            config_pins=(config_pin,),
            contract_pins=(contract_pin,),
            image_digest="sha256:" + "b" * 64,
            sbom_pin=sbom_pin,
        ),
        "evidence": evidence,
        "findings": (
            FindingDisposition(
                finding_id="P1-accepted-example",
                severity="P1",
                disposition="accepted",
                risk_owner="risk@example.com",
                rationale="bounded canary exception",
                accepted_until=NOW + timedelta(days=7),
            ),
        ),
        "drills": drills,
        "wallet": WalletFundingCheck(
            cluster="mainnet-beta",
            wallet_pubkey=WALLET,
            observed_balance_lamports=30_000_000,
            protected_reserve_lamports=15_000_000,
            fee_buffer_lamports=5_000_000,
            ownership_verified=True,
            signer_reference="keychain:flashloan-canary",
            signer_reference_verified=True,
            checked_at=NOW,
            checker="operator@example.com",
        ),
        "ownership_checks": ownership,
        "external_contract_drift": ExternalContractDriftEvidence(
            report_pin=drift_pin,
            checked_at=NOW,
            registry_schema_version="pr027.external-contracts.v1",
            ok=True,
            diagnostic="verified",
        ),
        "rollout": RolloutPlan(
            stages=(
                RolloutStage(
                    name="shadow",
                    minimum_duration_seconds=86_400,
                    maximum_exposure_lamports=0,
                    promotion_criteria=("PR-039 evidence reviewed",),
                    rollback_triggers=("any reconciliation mismatch",),
                ),
                RolloutStage(
                    name="canary",
                    minimum_duration_seconds=86_400,
                    maximum_exposure_lamports=1_000_000,
                    promotion_criteria=("PR-046 evidence reviewed",),
                    rollback_triggers=("any ambiguous submission",),
                ),
                RolloutStage(
                    name="limited-live",
                    minimum_duration_seconds=172_800,
                    maximum_exposure_lamports=2_000_000,
                    promotion_criteria=("all PR-047 signoffs",),
                    rollback_triggers=("any safety latch",),
                ),
            ),
            rollback_runbook_pin=rollback_pin,
            post_release_monitoring_seconds=86_400,
            on_call_owner="oncall@example.com",
            manual_promotion_required=True,
        ),
        "signoffs": signoffs,
        "verifications": verifications,
        "notes": "No runtime enablement is performed by this manifest.",
    }
    payload.update(changes)
    draft = ReleaseManifest.model_validate(payload)
    payload["expected_manifest_sha256"] = draft.manifest_sha256
    return ReleaseManifest.model_validate(payload)


def _evaluate(root: Path, manifest: ReleaseManifest):
    return ReleaseGate(
        repo_root=root,
        observed_code_commit=COMMIT,
        observed_contract_drift_ok=True,
        evaluated_at=NOW,
    ).evaluate(manifest)


def test_complete_evidence_is_deterministic_and_ready(tmp_path: Path) -> None:
    first = _manifest(tmp_path)
    second = ReleaseManifest.model_validate_json(first.model_dump_json())
    assert first.manifest_sha256 == second.manifest_sha256

    result = _evaluate(tmp_path, first)
    assert result.production_ready is True
    assert result.state == "production-ready"
    assert not result.blockers
    assert result.warnings == (
        "DOCUMENTED_RISK_ACCEPTANCE:P1-accepted-example:risk@example.com",
    )


def test_pr046_evidence_is_mandatory(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    incomplete = _manifest(tmp_path, evidence=(manifest.evidence[0],))
    result = _evaluate(tmp_path, incomplete)
    assert result.production_ready is False
    assert "REQUIRED_PR039_PR046_EVIDENCE_MISSING" in result.blockers


def test_one_green_ci_is_not_release_evidence(tmp_path: Path) -> None:
    ci_only = (
        VerificationRecord(
            kind=VerificationKind.REPOSITORY_CI,
            identifier="ci-1",
            status="passed",
            observed_at=NOW,
        ),
    )
    result = _evaluate(tmp_path, _manifest(tmp_path, verifications=ci_only))
    assert "SINGLE_GREEN_CI_IS_NOT_RELEASE_EVIDENCE" in result.blockers
    assert "OPERATIONAL_REHEARSAL_VERIFICATION_MISSING" in result.blockers
    assert "REPRODUCIBLE_ARTIFACT_REBUILD_MISSING" in result.blockers


def test_open_p0_and_expired_acceptance_block(tmp_path: Path) -> None:
    findings = (
        FindingDisposition(
            finding_id="P0-open",
            severity="P0",
            disposition="open",
        ),
        FindingDisposition(
            finding_id="P1-expired",
            severity="P1",
            disposition="accepted",
            risk_owner="risk@example.com",
            rationale="temporary",
            accepted_until=NOW - timedelta(seconds=1),
        ),
    )
    result = _evaluate(tmp_path, _manifest(tmp_path, findings=findings))
    assert "OPEN_P0_FINDING:P0-open" in result.blockers
    assert "RISK_ACCEPTANCE_EXPIRED:P1-expired" in result.blockers


def test_key_rotation_and_rollback_must_be_actual_rehearsals(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    drills = tuple(
        (
            item.model_copy(update={"simulated": True})
            if item.kind in {DrillKind.KEY_ROTATION, DrillKind.ROLLBACK}
            else item
        )
        for item in manifest.drills
    )
    result = _evaluate(tmp_path, _manifest(tmp_path, drills=drills))
    assert "DRILL_NOT_ACTUALLY_REHEARSED:key-rotation" in result.blockers
    assert "DRILL_NOT_ACTUALLY_REHEARSED:rollback" in result.blockers


def test_tampered_artifact_and_low_wallet_balance_block(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    (tmp_path / manifest.artifacts.sbom_pin.path).write_text(
        "tampered\n", encoding="utf-8"
    )
    low_wallet = manifest.wallet.model_copy(update={"observed_balance_lamports": 1})
    result = _evaluate(tmp_path, manifest.model_copy(update={"wallet": low_wallet}))
    assert (
        f"PIN_MISSING_OR_MISMATCH:{manifest.artifacts.sbom_pin.path}" in result.blockers
    )
    assert "WALLET_BALANCE_BELOW_RESERVE_AND_FEE_BUFFER" in result.blockers


def test_current_contract_drift_revalidation_is_not_optional(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    result = ReleaseGate(
        repo_root=tmp_path,
        observed_code_commit=COMMIT,
        observed_contract_drift_ok=False,
        evaluated_at=NOW,
    ).evaluate(manifest)
    assert "CURRENT_EXTERNAL_CONTRACT_DRIFT_REVALIDATION_FAILED" in result.blockers


def test_inline_signer_or_credential_material_is_rejected() -> None:
    with pytest.raises(ValidationError, match="signer_reference"):
        WalletFundingCheck(
            cluster="mainnet-beta",
            wallet_pubkey=WALLET,
            observed_balance_lamports=1,
            protected_reserve_lamports=0,
            fee_buffer_lamports=0,
            ownership_verified=True,
            signer_reference="plaintext-private-key",
            signer_reference_verified=True,
            checked_at=NOW,
            checker="operator",
        )
    with pytest.raises(ValidationError, match="credential_reference"):
        AccountOwnershipCheck(
            kind=OwnershipKind.RPC,
            account_reference="account",
            owner="owner",
            billing_owner="billing",
            credential_reference="secret-token-value",
            ownership_verified=True,
            credential_rotation_owner_verified=True,
            checked_at=NOW,
            checker="checker",
        )
