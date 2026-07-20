"""Strict release-evidence models for roadmap PR-047.

The models are intentionally transport-neutral and never enable a sender.  They
only describe the evidence required before a human may declare a release
production-ready.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = "pr047.production-release-gate.v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_PUBKEY_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
_SECRET_REFERENCE_PREFIXES = ("env:", "file:/", "keychain:")


def stable_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def sha256_json(payload: Any) -> str:
    return hashlib.sha256(stable_json(payload).encode("utf-8")).hexdigest()


class FrozenStrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class PinKind(StrEnum):
    CONFIG = "config"
    CONTRACT = "contract"
    SBOM = "sbom"
    EVIDENCE = "evidence"
    DRILL = "drill"
    RUNBOOK = "runbook"


class EvidenceKind(StrEnum):
    PR039_SHADOW_SOAK = "pr039-shadow-soak"
    PR046_LIMITED_LIVE_CANARY = "pr046-limited-live-canary"


class DrillKind(StrEnum):
    RESTORE = "restore"
    RESTART = "restart"
    KEY_ROTATION = "key-rotation"
    KILL_SWITCH = "kill-switch"
    ROLLBACK = "rollback"


class OwnershipKind(StrEnum):
    RPC = "rpc"
    PROVIDER = "provider"
    JITO = "jito"


class SignoffRole(StrEnum):
    RELEASE_MANAGER = "release-manager"
    RISK_OWNER = "risk-owner"
    SECURITY_OWNER = "security-owner"
    OPERATOR = "operator"


class VerificationKind(StrEnum):
    REPOSITORY_CI = "repository-ci"
    ARTIFACT_REBUILD = "artifact-rebuild"
    SBOM_BUILD = "sbom-build"
    EXTERNAL_CONTRACT_DRIFT = "external-contract-drift"
    OPERATIONAL_REHEARSAL = "operational-rehearsal"
    SECURITY_GATE = "security-gate"


class FilePin(FrozenStrictModel):
    path: str
    sha256: str
    kind: PinKind

    @field_validator("path")
    @classmethod
    def normalized_relative_path(cls, value: str) -> str:
        normalized = value.replace("\\", "/")
        parts = normalized.split("/")
        if (
            not value
            or value.startswith(("/", "~"))
            or any(part in {"", ".", ".."} for part in parts)
        ):
            raise ValueError("path must be a normalized repository-relative path")
        return normalized

    @field_validator("sha256")
    @classmethod
    def real_sha256(cls, value: str) -> str:
        lowered = value.lower()
        if not _SHA256_RE.fullmatch(lowered) or lowered == "0" * 64:
            raise ValueError("sha256 must be a non-placeholder lowercase digest")
        return lowered


class ReleaseArtifacts(FrozenStrictModel):
    code_commit: str
    config_pins: tuple[FilePin, ...] = Field(min_length=1)
    contract_pins: tuple[FilePin, ...] = Field(min_length=1)
    image_digest: str
    sbom_pin: FilePin

    @field_validator("code_commit")
    @classmethod
    def git_commit(cls, value: str) -> str:
        lowered = value.lower()
        if not _GIT_SHA_RE.fullmatch(lowered) or lowered == "0" * 40:
            raise ValueError("code_commit must be a full non-placeholder git SHA")
        return lowered

    @field_validator("image_digest")
    @classmethod
    def image_sha256(cls, value: str) -> str:
        prefix = "sha256:"
        if not value.startswith(prefix) or not _SHA256_RE.fullmatch(
            value[len(prefix) :]
        ):
            raise ValueError("image_digest must use sha256:<64 lowercase hex>")
        if value == prefix + "0" * 64:
            raise ValueError("image_digest cannot be a placeholder")
        return value

    @model_validator(mode="after")
    def pin_kinds(self) -> "ReleaseArtifacts":
        if any(pin.kind is not PinKind.CONFIG for pin in self.config_pins):
            raise ValueError("config_pins must all use kind=config")
        if any(pin.kind is not PinKind.CONTRACT for pin in self.contract_pins):
            raise ValueError("contract_pins must all use kind=contract")
        if self.sbom_pin.kind is not PinKind.SBOM:
            raise ValueError("sbom_pin must use kind=sbom")
        paths = [
            *(pin.path for pin in self.config_pins),
            *(pin.path for pin in self.contract_pins),
            self.sbom_pin.path,
        ]
        if len(paths) != len(set(paths)):
            raise ValueError("release artifact pin paths must be unique")
        return self


class EvidenceReference(FrozenStrictModel):
    kind: EvidenceKind
    schema_version: str
    pin: FilePin
    passed: bool
    human_reviewed: bool
    reviewer: str
    reviewed_at: datetime

    @model_validator(mode="after")
    def evidence_contract(self) -> "EvidenceReference":
        if self.pin.kind is not PinKind.EVIDENCE:
            raise ValueError("evidence pin must use kind=evidence")
        if not self.reviewer.strip():
            raise ValueError("evidence reviewer is required")
        if self.reviewed_at.tzinfo is None or self.reviewed_at.utcoffset() is None:
            raise ValueError("reviewed_at must be timezone-aware")
        return self


class FindingDisposition(FrozenStrictModel):
    finding_id: str
    severity: Literal["P0", "P1", "P2", "P3"]
    disposition: Literal["closed", "accepted", "open"]
    risk_owner: str | None = None
    rationale: str | None = None
    accepted_until: datetime | None = None

    @model_validator(mode="after")
    def risk_acceptance(self) -> "FindingDisposition":
        if not self.finding_id.strip():
            raise ValueError("finding_id is required")
        if self.disposition == "accepted":
            if not self.risk_owner or not self.risk_owner.strip():
                raise ValueError("accepted finding requires risk_owner")
            if not self.rationale or not self.rationale.strip():
                raise ValueError("accepted finding requires rationale")
            if self.accepted_until is None:
                raise ValueError("accepted finding requires accepted_until")
            if (
                self.accepted_until.tzinfo is None
                or self.accepted_until.utcoffset() is None
            ):
                raise ValueError("accepted_until must be timezone-aware")
        return self


class DrillRecord(FrozenStrictModel):
    kind: DrillKind
    performed_at: datetime
    operator: str
    environment: str
    passed: bool
    simulated: bool = False
    evidence_pin: FilePin
    notes: str = ""

    @model_validator(mode="after")
    def drill_contract(self) -> "DrillRecord":
        if self.evidence_pin.kind is not PinKind.DRILL:
            raise ValueError("drill evidence must use kind=drill")
        if self.performed_at.tzinfo is None or self.performed_at.utcoffset() is None:
            raise ValueError("performed_at must be timezone-aware")
        if not self.operator.strip() or not self.environment.strip():
            raise ValueError("drill operator and environment are required")
        return self


class WalletFundingCheck(FrozenStrictModel):
    cluster: Literal["mainnet-beta"]
    wallet_pubkey: str
    observed_balance_lamports: int = Field(ge=0)
    protected_reserve_lamports: int = Field(ge=0)
    fee_buffer_lamports: int = Field(ge=0)
    ownership_verified: bool
    signer_reference: str
    signer_reference_verified: bool
    checked_at: datetime
    checker: str

    @field_validator("wallet_pubkey")
    @classmethod
    def valid_pubkey(cls, value: str) -> str:
        if not _PUBKEY_RE.fullmatch(value):
            raise ValueError("wallet_pubkey must be a valid base58 public key")
        return value

    @field_validator("signer_reference")
    @classmethod
    def secret_reference_only(cls, value: str) -> str:
        if not value.startswith(_SECRET_REFERENCE_PREFIXES):
            raise ValueError("signer_reference must be env:, file:/, or keychain:")
        return value

    @model_validator(mode="after")
    def wallet_contract(self) -> "WalletFundingCheck":
        if self.checked_at.tzinfo is None or self.checked_at.utcoffset() is None:
            raise ValueError("checked_at must be timezone-aware")
        if not self.checker.strip():
            raise ValueError("wallet checker is required")
        return self


class AccountOwnershipCheck(FrozenStrictModel):
    kind: OwnershipKind
    account_reference: str
    owner: str
    billing_owner: str
    credential_reference: str
    ownership_verified: bool
    credential_rotation_owner_verified: bool
    checked_at: datetime
    checker: str

    @field_validator("credential_reference")
    @classmethod
    def secret_reference_only(cls, value: str) -> str:
        if not value.startswith(_SECRET_REFERENCE_PREFIXES):
            raise ValueError("credential_reference must be env:, file:/, or keychain:")
        return value

    @model_validator(mode="after")
    def ownership_contract(self) -> "AccountOwnershipCheck":
        for label, value in (
            ("account_reference", self.account_reference),
            ("owner", self.owner),
            ("billing_owner", self.billing_owner),
            ("checker", self.checker),
        ):
            if not value.strip():
                raise ValueError(f"{label} is required")
        if self.checked_at.tzinfo is None or self.checked_at.utcoffset() is None:
            raise ValueError("checked_at must be timezone-aware")
        return self


class ExternalContractDriftEvidence(FrozenStrictModel):
    report_pin: FilePin
    checked_at: datetime
    registry_schema_version: str
    ok: bool
    diagnostic: str

    @model_validator(mode="after")
    def drift_contract(self) -> "ExternalContractDriftEvidence":
        if self.report_pin.kind is not PinKind.EVIDENCE:
            raise ValueError("drift report pin must use kind=evidence")
        if self.checked_at.tzinfo is None or self.checked_at.utcoffset() is None:
            raise ValueError("checked_at must be timezone-aware")
        return self


class RolloutStage(FrozenStrictModel):
    name: Literal["shadow", "canary", "limited-live"]
    minimum_duration_seconds: int = Field(gt=0)
    maximum_exposure_lamports: int = Field(ge=0)
    promotion_criteria: tuple[str, ...] = Field(min_length=1)
    rollback_triggers: tuple[str, ...] = Field(min_length=1)
    rollback_target: Literal["shadow"] = "shadow"


class RolloutPlan(FrozenStrictModel):
    stages: tuple[RolloutStage, ...]
    rollback_runbook_pin: FilePin
    post_release_monitoring_seconds: int = Field(ge=24 * 60 * 60)
    on_call_owner: str
    manual_promotion_required: bool = True

    @model_validator(mode="after")
    def rollout_contract(self) -> "RolloutPlan":
        if tuple(stage.name for stage in self.stages) != (
            "shadow",
            "canary",
            "limited-live",
        ):
            raise ValueError("rollout stages must be shadow, canary, limited-live")
        if self.rollback_runbook_pin.kind is not PinKind.RUNBOOK:
            raise ValueError("rollback runbook must use kind=runbook")
        if not self.on_call_owner.strip():
            raise ValueError("on_call_owner is required")
        if not self.manual_promotion_required:
            raise ValueError("manual promotion cannot be disabled")
        return self


class Signoff(FrozenStrictModel):
    role: SignoffRole
    identity: str
    decision: Literal["approve", "block"]
    signed_at: datetime
    comment: str = ""

    @model_validator(mode="after")
    def signoff_contract(self) -> "Signoff":
        if not self.identity.strip():
            raise ValueError("signoff identity is required")
        if self.signed_at.tzinfo is None or self.signed_at.utcoffset() is None:
            raise ValueError("signed_at must be timezone-aware")
        return self


class VerificationRecord(FrozenStrictModel):
    kind: VerificationKind
    identifier: str
    status: Literal["passed", "failed"]
    observed_at: datetime
    evidence_pin: FilePin | None = None

    @model_validator(mode="after")
    def verification_contract(self) -> "VerificationRecord":
        if not self.identifier.strip():
            raise ValueError("verification identifier is required")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        if (
            self.evidence_pin is not None
            and self.evidence_pin.kind is not PinKind.EVIDENCE
        ):
            raise ValueError("verification evidence must use kind=evidence")
        return self


class ReleaseManifest(FrozenStrictModel):
    schema_version: str = SCHEMA_VERSION
    release_id: str
    generated_at: datetime
    expected_manifest_sha256: str
    artifacts: ReleaseArtifacts
    evidence: tuple[EvidenceReference, ...]
    findings: tuple[FindingDisposition, ...]
    drills: tuple[DrillRecord, ...]
    wallet: WalletFundingCheck
    ownership_checks: tuple[AccountOwnershipCheck, ...]
    external_contract_drift: ExternalContractDriftEvidence
    rollout: RolloutPlan
    signoffs: tuple[Signoff, ...]
    verifications: tuple[VerificationRecord, ...]
    notes: str = ""

    @field_validator("expected_manifest_sha256")
    @classmethod
    def expected_hash(cls, value: str) -> str:
        lowered = value.lower()
        if not _SHA256_RE.fullmatch(lowered):
            raise ValueError("expected_manifest_sha256 must be 64 lowercase hex chars")
        return lowered

    @model_validator(mode="after")
    def manifest_contract(self) -> "ReleaseManifest":
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported release manifest schema")
        if not self.release_id.strip():
            raise ValueError("release_id is required")
        if self.generated_at.tzinfo is None or self.generated_at.utcoffset() is None:
            raise ValueError("generated_at must be timezone-aware")
        evidence_kinds = [item.kind for item in self.evidence]
        if len(evidence_kinds) != len(set(evidence_kinds)):
            raise ValueError("evidence kinds must be unique")
        finding_ids = [item.finding_id for item in self.findings]
        if len(finding_ids) != len(set(finding_ids)):
            raise ValueError("finding ids must be unique")
        drill_kinds = [item.kind for item in self.drills]
        if len(drill_kinds) != len(set(drill_kinds)):
            raise ValueError("drill kinds must be unique")
        ownership_kinds = [item.kind for item in self.ownership_checks]
        if len(ownership_kinds) != len(set(ownership_kinds)):
            raise ValueError("ownership check kinds must be unique")
        signoff_roles = [item.role for item in self.signoffs]
        if len(signoff_roles) != len(set(signoff_roles)):
            raise ValueError("signoff roles must be unique")
        return self

    def canonical_payload(self) -> dict[str, Any]:
        payload = self.model_dump(mode="json")
        payload.pop("expected_manifest_sha256", None)
        return payload

    @property
    def manifest_sha256(self) -> str:
        return sha256_json(self.canonical_payload())

    @property
    def generated_at_utc(self) -> datetime:
        return self.generated_at.astimezone(timezone.utc)
