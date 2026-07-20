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
)
from .supply_chain import (
    DependencyAuditPolicy,
    Severity,
    SupplyChainDecision,
    VulnerabilityRecord,
)

__all__ = [
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
    "scan_mapping_for_key_material",
    "scan_text_for_key_material",
]
