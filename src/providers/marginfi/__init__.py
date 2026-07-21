"""PR-028 binary MarginFi provider; promotion awaits PR-027 and RPC evidence."""

# The implementation is binary/source-conformant, but the repository capability
# remains quarantined until PR-027 is merged and opt-in mainnet evidence passes.
__runtime_capability__ = "fixture-only"
__quarantined__ = True

from .accounts import (
    BankSnapshot,
    MarginAccountSnapshot,
    MarginfiAccountReader,
    MarginfiSnapshot,
    ReadonlyAccountPort,
    RpcAccount,
)
from .complete_evidence import (
    MAXIMUM_SHADOW_CAPABILITY,
    MarginfiCompleteEvidenceError,
    MarginfiCompleteEvidenceEvaluation,
    assert_marginfi_complete_evidence,
    evaluate_marginfi_complete_evidence,
    load_marginfi_complete_evidence_manifest,
)
from .errors import MarginfiRejection, MarginfiRejectionCode
from .pin import MarginfiContractPin, load_marginfi_contract_pin
from .protocol_conformance import (
    MarginfiAccountVector,
    MarginfiAccountVectorKind,
    MarginfiFlashloanMetaEvidence,
    MarginfiHumanReviewEvidence,
    MarginfiInstructionVector,
    MarginfiProtocolArtifact,
    MarginfiProtocolArtifactKind,
    MarginfiProtocolConformanceEvaluation,
    MarginfiProtocolConformanceEvidence,
    MarginfiProtocolConformanceError,
    MarginfiProtocolConformanceThresholds,
    MarginfiReadonlyRpcEvidence,
    MarginfiRepaymentMathEvidence,
    MarginfiToken2022Evidence,
    assert_marginfi_protocol_conformance,
    evaluate_marginfi_protocol_conformance,
)
from .provider import (
    FinalizedMarginfiFlashLoanPlan,
    MarginfiFlashLoanProvider,
    PreparedMarginfiFlashLoan,
)

__all__ = [
    "BankSnapshot",
    "FinalizedMarginfiFlashLoanPlan",
    "MAXIMUM_SHADOW_CAPABILITY",
    "MarginAccountSnapshot",
    "MarginfiAccountReader",
    "MarginfiAccountVector",
    "MarginfiAccountVectorKind",
    "MarginfiCompleteEvidenceError",
    "MarginfiCompleteEvidenceEvaluation",
    "MarginfiContractPin",
    "MarginfiFlashLoanProvider",
    "MarginfiFlashloanMetaEvidence",
    "MarginfiHumanReviewEvidence",
    "MarginfiInstructionVector",
    "MarginfiProtocolArtifact",
    "MarginfiProtocolArtifactKind",
    "MarginfiProtocolConformanceEvaluation",
    "MarginfiProtocolConformanceEvidence",
    "MarginfiProtocolConformanceError",
    "MarginfiProtocolConformanceThresholds",
    "MarginfiRejection",
    "MarginfiRejectionCode",
    "MarginfiReadonlyRpcEvidence",
    "MarginfiRepaymentMathEvidence",
    "MarginfiSnapshot",
    "MarginfiToken2022Evidence",
    "PreparedMarginfiFlashLoan",
    "ReadonlyAccountPort",
    "RpcAccount",
    "assert_marginfi_complete_evidence",
    "assert_marginfi_protocol_conformance",
    "evaluate_marginfi_complete_evidence",
    "evaluate_marginfi_protocol_conformance",
    "load_marginfi_complete_evidence_manifest",
    "load_marginfi_contract_pin",
]
