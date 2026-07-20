"""Security boundary primitives for PR-043 wallet and supply-chain hardening."""

from .secret_scan import (
    PlaintextKeyMaterialError,
    SecretScanFinding,
    assert_no_plaintext_key_material,
    scan_mapping_for_key_material,
    scan_text_for_key_material,
)
from .signer_policy import (
    SignerPolicy,
    SignerPolicyError,
    SignerPolicyPermit,
    UnsignedMessage,
    build_signer_policy,
)
from .supply_chain import (
    DEFAULT_DEPENDENCY_AUDIT_POLICY,
    DependencyAuditPolicy,
    Severity,
    SupplyChainDecision,
    VulnerabilityRecord,
)

__all__ = [
    "DEFAULT_DEPENDENCY_AUDIT_POLICY",
    "DependencyAuditPolicy",
    "PlaintextKeyMaterialError",
    "SecretScanFinding",
    "Severity",
    "SignerPolicy",
    "SignerPolicyError",
    "SignerPolicyPermit",
    "SupplyChainDecision",
    "UnsignedMessage",
    "VulnerabilityRecord",
    "assert_no_plaintext_key_material",
    "build_signer_policy",
    "scan_mapping_for_key_material",
    "scan_text_for_key_material",
]
