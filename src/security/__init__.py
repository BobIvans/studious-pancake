"""Security boundaries for the installed sender-free runtime."""

from .archives import ArchiveLimits, ArchiveSecurityError, validate_tar, validate_zip
from .filesystem import FilesystemSecurityError, atomic_write_bytes, resolve_owned_path
from .input_limits import (
    InputLimits,
    InputSecurityError,
    decode_bounded_json,
    decode_bounded_json_object,
)
from .network import NetworkSecurityError, UrlPolicy, validate_url
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
from .subprocess import SubprocessPolicy, SubprocessSecurityError, run_allowlisted
from .supply_chain import (
    DEFAULT_DEPENDENCY_AUDIT_POLICY,
    DependencyAuditPolicy,
    Severity,
    SupplyChainDecision,
    VulnerabilityRecord,
)

__all__ = [
    "ArchiveLimits",
    "ArchiveSecurityError",
    "DEFAULT_DEPENDENCY_AUDIT_POLICY",
    "DependencyAuditPolicy",
    "ErrorCategory",
    "FilesystemSecurityError",
    "InputLimits",
    "InputSecurityError",
    "NetworkSecurityError",
    "ParserInvariantError",
    "ParserInvariantFinding",
    "PlaintextKeyMaterialError",
    "SecretScanFinding",
    "Severity",
    "SignerPolicy",
    "SignerPolicyError",
    "SignerPolicyPermit",
    "SubprocessPolicy",
    "SubprocessSecurityError",
    "SupplyChainDecision",
    "UnsignedMessage",
    "UrlPolicy",
    "VulnerabilityRecord",
    "assert_no_parser_invariant_debt",
    "assert_no_plaintext_key_material",
    "atomic_write_bytes",
    "build_signer_policy",
    "decode_bounded_json",
    "decode_bounded_json_object",
    "parse_json_object_payload",
    "require_invariant",
    "resolve_owned_path",
    "run_allowlisted",
    "scan_mapping_for_key_material",
    "scan_python_paths_for_invariant_debt",
    "scan_python_source_for_invariant_debt",
    "scan_text_for_key_material",
    "validate_tar",
    "validate_url",
    "validate_zip",
]
