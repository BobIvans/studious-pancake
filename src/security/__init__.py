"""Security boundary primitives for PR-043 wallet and supply-chain hardening."""

from .parser_invariants import (
    ErrorCategory,
    ParserInvariantError,
    ParserInvariantFinding,
    assert_no_parser_invariant_debt,
    parse_json_object_payload,
    require_invariant,
    scan_python_paths_for_invariant_debt,
    scan_python_source_for_invariant_debt,
)
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
    "ErrorCategory",
    "ParserInvariantError",
    "ParserInvariantFinding",
    "PlaintextKeyMaterialError",
    "SecretScanFinding",
    "Severity",
    "SignerPolicy",
    "SignerPolicyError",
    "SignerPolicyPermit",
    "SupplyChainDecision",
    "UnsignedMessage",
    "VulnerabilityRecord",
    "assert_no_parser_invariant_debt",
    "assert_no_plaintext_key_material",
    "build_signer_policy",
    "parse_json_object_payload",
    "require_invariant",
    "scan_mapping_for_key_material",
    "scan_python_paths_for_invariant_debt",
    "scan_python_source_for_invariant_debt",
    "scan_text_for_key_material",
]
