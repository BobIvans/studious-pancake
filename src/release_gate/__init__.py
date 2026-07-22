"""Lazy PR-047 production release evidence gate exports.

Importing ``src.release_gate.models`` must not eagerly import canary or shadow-soak
modules.  PR-146 keeps the package re-export API while resolving heavy symbols only
when a caller explicitly asks for them.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .actual_evidence import (
        REQUIRED_ACTUAL_EVIDENCE_KINDS,
        ActualEvidenceArtifact,
        ActualEvidenceGate,
        ActualEvidenceGateResult,
        ActualEvidenceKind,
        ActualEvidencePackage,
    )
    from .gate import ReleaseGate, ReleaseGateResult
    from .limited_canary import (
        CANARY_RELEASE_RESULT_SCHEMA_VERSION,
        CANARY_RELEASE_SCHEMA_VERSION,
        CANARY_RUNTIME_REQUEST_SCHEMA_VERSION,
        CANARY_RUNTIME_RESULT_SCHEMA_VERSION,
        PR078_SECURITY_EVIDENCE_NAME,
        PR080_SENDER_CONFORMANCE_NAME,
        PR092_REAL_SOAK_EVIDENCE_NAME,
        PR093_SENDER_LIFECYCLE_NAME,
        REQUIRED_ENABLEMENT_STEPS,
        REQUIRED_LATCHES,
        REQUIRED_MANIFEST_HASHES,
        REQUIRED_RUNTIME_ACKS,
        REQUIRED_SENDER_CONTROLS,
        EvidenceRef,
        LimitedCanaryError,
        LimitedCanaryPackage,
        LimitedCanaryReadiness,
        LimitedCanaryRuntimeReadiness,
        LimitedCanaryRuntimeRequest,
        LimitedCanaryRuntimeState,
        LimitedCanaryState,
        evaluate_limited_canary,
        evaluate_limited_canary_runtime_request,
    )
    from .models import (
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
        ReleaseManifest,
        RolloutPlan,
        RolloutStage,
        Signoff,
        SignoffRole,
        VerificationKind,
        VerificationRecord,
        WalletFundingCheck,
    )
    from .operational_drills import (
        DEFAULT_REQUIRED_FAILURE_AREAS,
        FailureInjectionScenario,
        OperationalDrillSuite,
        OperationalFailureArea,
        OperationalReadinessGate,
        OperationalReadinessResult,
        SecurityOperationalEvidence,
    )
    from .real_evidence_manifest import (
        PR091_RELEASE_ARTIFACT_ROOT,
        RealEvidenceManifestError,
        RealEvidenceManifestLoadResult,
        evaluate_pr091_actual_evidence_manifest,
        load_pr091_actual_evidence_manifest,
        load_pr091_actual_evidence_package,
    )
    from .reviewed_canary import (
        MAX_TINY_EXPOSURE_LAMPORTS,
        PR104_RELEASE_EVIDENCE_NAME,
        PR105_SHADOW_SOAK_EVIDENCE_NAME,
        PR106_SENDER_LIFECYCLE_EVIDENCE_NAME,
        PR107_REVIEWED_CANARY_RESULT_SCHEMA,
        PR107_REVIEWED_CANARY_SCHEMA,
        PR107_TYPE,
        REQUIRED_PR107_LATCHES,
        REQUIRED_PR107_SIGNOFFS,
        ReviewedCanaryAllowlistEntry,
        ReviewedCanaryError,
        ReviewedCanaryEvidenceRef,
        ReviewedCanaryLatch,
        ReviewedCanaryReadiness,
        ReviewedCanaryState,
        ReviewedLimitedCanaryPackage,
        evaluate_pr107_reviewed_canary_package,
    )

_EXPORTS: dict[str, str] = {
    "REQUIRED_ACTUAL_EVIDENCE_KINDS": ".actual_evidence",
    "ActualEvidenceArtifact": ".actual_evidence",
    "ActualEvidenceGate": ".actual_evidence",
    "ActualEvidenceGateResult": ".actual_evidence",
    "ActualEvidenceKind": ".actual_evidence",
    "ActualEvidencePackage": ".actual_evidence",
    "ReleaseGate": ".gate",
    "ReleaseGateResult": ".gate",
    "CANARY_RELEASE_RESULT_SCHEMA_VERSION": ".limited_canary",
    "CANARY_RELEASE_SCHEMA_VERSION": ".limited_canary",
    "CANARY_RUNTIME_REQUEST_SCHEMA_VERSION": ".limited_canary",
    "CANARY_RUNTIME_RESULT_SCHEMA_VERSION": ".limited_canary",
    "PR078_SECURITY_EVIDENCE_NAME": ".limited_canary",
    "PR080_SENDER_CONFORMANCE_NAME": ".limited_canary",
    "PR092_REAL_SOAK_EVIDENCE_NAME": ".limited_canary",
    "PR093_SENDER_LIFECYCLE_NAME": ".limited_canary",
    "REQUIRED_ENABLEMENT_STEPS": ".limited_canary",
    "REQUIRED_LATCHES": ".limited_canary",
    "REQUIRED_MANIFEST_HASHES": ".limited_canary",
    "REQUIRED_RUNTIME_ACKS": ".limited_canary",
    "REQUIRED_SENDER_CONTROLS": ".limited_canary",
    "EvidenceRef": ".limited_canary",
    "LimitedCanaryError": ".limited_canary",
    "LimitedCanaryPackage": ".limited_canary",
    "LimitedCanaryReadiness": ".limited_canary",
    "LimitedCanaryRuntimeReadiness": ".limited_canary",
    "LimitedCanaryRuntimeRequest": ".limited_canary",
    "LimitedCanaryRuntimeState": ".limited_canary",
    "LimitedCanaryState": ".limited_canary",
    "evaluate_limited_canary": ".limited_canary",
    "evaluate_limited_canary_runtime_request": ".limited_canary",
    "AccountOwnershipCheck": ".models",
    "DrillKind": ".models",
    "DrillRecord": ".models",
    "EvidenceKind": ".models",
    "EvidenceReference": ".models",
    "ExternalContractDriftEvidence": ".models",
    "FilePin": ".models",
    "FindingDisposition": ".models",
    "OwnershipKind": ".models",
    "PinKind": ".models",
    "ReleaseArtifacts": ".models",
    "ReleaseManifest": ".models",
    "RolloutPlan": ".models",
    "RolloutStage": ".models",
    "Signoff": ".models",
    "SignoffRole": ".models",
    "VerificationKind": ".models",
    "VerificationRecord": ".models",
    "WalletFundingCheck": ".models",
    "DEFAULT_REQUIRED_FAILURE_AREAS": ".operational_drills",
    "FailureInjectionScenario": ".operational_drills",
    "OperationalDrillSuite": ".operational_drills",
    "OperationalFailureArea": ".operational_drills",
    "OperationalReadinessGate": ".operational_drills",
    "OperationalReadinessResult": ".operational_drills",
    "SecurityOperationalEvidence": ".operational_drills",
    "PR091_RELEASE_ARTIFACT_ROOT": ".real_evidence_manifest",
    "RealEvidenceManifestError": ".real_evidence_manifest",
    "RealEvidenceManifestLoadResult": ".real_evidence_manifest",
    "evaluate_pr091_actual_evidence_manifest": ".real_evidence_manifest",
    "load_pr091_actual_evidence_manifest": ".real_evidence_manifest",
    "load_pr091_actual_evidence_package": ".real_evidence_manifest",
    "MAX_TINY_EXPOSURE_LAMPORTS": ".reviewed_canary",
    "PR104_RELEASE_EVIDENCE_NAME": ".reviewed_canary",
    "PR105_SHADOW_SOAK_EVIDENCE_NAME": ".reviewed_canary",
    "PR106_SENDER_LIFECYCLE_EVIDENCE_NAME": ".reviewed_canary",
    "PR107_REVIEWED_CANARY_RESULT_SCHEMA": ".reviewed_canary",
    "PR107_REVIEWED_CANARY_SCHEMA": ".reviewed_canary",
    "PR107_TYPE": ".reviewed_canary",
    "REQUIRED_PR107_LATCHES": ".reviewed_canary",
    "REQUIRED_PR107_SIGNOFFS": ".reviewed_canary",
    "ReviewedCanaryAllowlistEntry": ".reviewed_canary",
    "ReviewedCanaryError": ".reviewed_canary",
    "ReviewedCanaryEvidenceRef": ".reviewed_canary",
    "ReviewedCanaryLatch": ".reviewed_canary",
    "ReviewedCanaryReadiness": ".reviewed_canary",
    "ReviewedCanaryState": ".reviewed_canary",
    "ReviewedLimitedCanaryPackage": ".reviewed_canary",
    "evaluate_pr107_reviewed_canary_package": ".reviewed_canary",
}

__all__ = tuple(_EXPORTS)


def __getattr__(name: str) -> Any:
    """Resolve release-gate re-exports lazily to keep package imports acyclic."""

    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name, __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted((*globals(), *__all__))
