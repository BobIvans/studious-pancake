"""PR-157 isolated signer, settlement, and reviewed release gate.

Side-effect-free evidence gate: no Keypair import, no RPC/Jito calls, no
signing, no submission and no live activation.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Mapping


FULL_TRANSACTION_WIRE_LIMIT_BYTES = 1232
MINIMUM_SOAK_SECONDS = 72 * 60 * 60


class ReleaseDecision(StrEnum):
    APPROVED = "approved"
    BLOCKED = "blocked"


class ReleaseFailureReason(StrEnum):
    LIVE_DEFAULT_ENABLED = "live_default_enabled"
    SINGLE_ENV_ENABLES_LIVE = "single_env_enables_live"
    PRIVATE_KEY_IN_NETWORK = "private_key_in_network"
    SIGNER_NOT_ISOLATED = "signer_not_isolated"
    UNSUPPORTED_SIGNER_BACKEND = "unsupported_signer_backend"
    AUTHORIZATION_INCOMPLETE = "authorization_incomplete"
    AUTHORIZATION_NOT_DURABLE = "authorization_not_durable"
    AUTHORIZATION_REPLAYABLE = "authorization_replayable"
    PLAIN_CALLER_PERMIT = "plain_caller_permit"
    SUBMISSION_STATE_AMBIGUOUS = "submission_state_ambiguous"
    AUTO_RESEND_ON_AMBIGUITY = "auto_resend_on_ambiguity"
    JITO_UNSAFE = "jito_unsafe"
    SETTLEMENT_NOT_FINALIZED = "settlement_not_finalized"
    SETTLEMENT_RECONCILIATION_MISSING = "settlement_reconciliation_missing"
    RELEASE_NOT_HERMETIC = "release_not_hermetic"
    SANDBOX_INCOMPLETE = "sandbox_incomplete"
    SOAK_INCOMPLETE = "soak_incomplete"
    OPERATOR_APPROVAL_MISSING = "operator_approval_missing"
    EXPOSURE_TOO_LARGE = "exposure_too_large"
    LATCH_MISSING = "latch_missing"
    INDETERMINATE_OUTCOME = "indeterminate_outcome"
    PLACEHOLDER_HASH = "placeholder_hash"


class SignerBackendKind(StrEnum):
    KMS = "kms"
    HSM = "hsm"
    VAULT = "vault"
    KEYCHAIN = "keychain"
    DEVELOPMENT_MEMORY = "development_memory"


class SubmissionState(StrEnum):
    SIGNING_INTENT = "signing_intent"
    SIGNED = "signed"
    SUBMISSION_INTENT = "submission_intent"
    DISPATCHED = "dispatched"
    ACKNOWLEDGED = "acknowledged"
    PROCESSED = "processed"
    CONFIRMED = "confirmed"
    FINALIZED = "finalized"
    UNKNOWN = "unknown"


class CanaryMode(StrEnum):
    PAPER_ONLY = "paper_only"
    REVIEWED_TINY_CANARY = "reviewed_tiny_canary"


_REQUIRED_AUTHORIZATION_BINDINGS = frozenset(
    {
        "attempt_generation",
        "exact_message_hash",
        "policy_bundle_hash",
        "program_attestation_hash",
        "asset_mint_attestation_hash",
        "marginfi_evidence_hash",
        "jupiter_evidence_hash",
        "simulation_cpi_proof_hash",
        "fee_blockhash_alt_fork_hash",
        "signer_pubkey",
        "expiry",
        "nonce",
    }
)
_PLACEHOLDER_HASHES = frozenset(
    {"", "0", "0" * 64, "1" * 64, "deadbeef", "todo", "pending"}
)


@dataclass(frozen=True, slots=True)
class SignerBoundaryEvidence:
    network_runtime_imports_keypair: bool
    network_runtime_has_private_key_bytes: bool
    signer_backend: SignerBackendKind
    signer_parses_exact_v0_message: bool
    signer_derives_payer_signers_programs_accounts: bool
    signer_verifies_policy_and_proof_hashes: bool
    signer_checks_full_wire_limit: bool
    signer_returns_signature_only: bool
    signer_has_general_network_access: bool
    signer_identity_hash: str
    backend_public_key_hash: str

    def __post_init__(self) -> None:
        _require_hash(self.signer_identity_hash, "signer_identity_hash")
        _require_hash(self.backend_public_key_hash, "backend_public_key_hash")


@dataclass(frozen=True, slots=True)
class AuthorizationEvidence:
    durable: bool
    authenticated: bool
    caller_constructable_plain_dataclass: bool
    one_time_nonce_persisted: bool
    expiry_unix_ms: int
    bindings: Mapping[str, str]
    authorization_hash: str

    def __post_init__(self) -> None:
        if self.expiry_unix_ms <= 0:
            raise ValueError("expiry_unix_ms must be positive")
        _require_hash(self.authorization_hash, "authorization_hash")


@dataclass(frozen=True, slots=True)
class SubmissionLifecycleEvidence:
    current_state: SubmissionState
    durable_signing_intent: bool
    signed_payload_verified: bool
    durable_submission_intent: bool
    auto_resend_on_ambiguity: bool
    ambiguity_latch_enabled: bool
    indeterminate_outcome: bool = False


@dataclass(frozen=True, slots=True)
class JitoSafetyEvidence:
    enabled: bool
    one_atomic_transaction: bool
    tip_inside_same_transaction: bool
    exactly_one_tip: bool
    current_tip_account_evidence_hash: str | None = None
    bundle_only_reviewed: bool = False
    standalone_tip_forbidden: bool = True
    uncle_unbundling_drill_hash: str | None = None


@dataclass(frozen=True, slots=True)
class FinalizedSettlementEvidence:
    finalized: bool
    get_transaction_max_supported_v0: bool
    exact_transaction_identity_hash: str
    meta_err_is_none: bool
    actual_fee_lamports: int
    native_token_balance_evidence_hash: str
    loaded_addresses_hash: str
    inner_instructions_cpi_hash: str
    compute_units_hash: str
    marginfi_repayment_hash: str
    rent_tip_transfer_fee_hash: str
    simulated_vs_actual_reconciliation_hash: str
    conservative_net_lamports: int

    def __post_init__(self) -> None:
        if self.actual_fee_lamports < 0:
            raise ValueError("actual_fee_lamports must be non-negative")
        for name in (
            "exact_transaction_identity_hash",
            "native_token_balance_evidence_hash",
            "loaded_addresses_hash",
            "inner_instructions_cpi_hash",
            "compute_units_hash",
            "marginfi_repayment_hash",
            "rent_tip_transfer_fee_hash",
            "simulated_vs_actual_reconciliation_hash",
        ):
            _require_hash(getattr(self, name), name)


@dataclass(frozen=True, slots=True)
class HermeticReleaseEvidence:
    github_actions_pinned_to_full_sha: bool
    docker_image_pinned_by_digest: bool
    hashed_wheelhouse: bool
    offline_reproducible_build: bool
    sbom_hash: str
    vulnerability_scan_hash: str
    license_inventory_hash: str
    secret_scan_hash: str
    signed_artifact_provenance_hash: str

    def __post_init__(self) -> None:
        for name in (
            "sbom_hash",
            "vulnerability_scan_hash",
            "license_inventory_hash",
            "secret_scan_hash",
            "signed_artifact_provenance_hash",
        ):
            _require_hash(getattr(self, name), name)


@dataclass(frozen=True, slots=True)
class ProductionSandboxEvidence:
    read_only_root_fs: bool
    capability_drop: bool
    no_new_privileges: bool
    seccomp_or_apparmor: bool
    cpu_memory_pid_fd_limits: bool
    egress_allowlist: bool
    signer_network_separation: bool


@dataclass(frozen=True, slots=True)
class ReviewedCanaryEvidence:
    mode: CanaryMode
    default_package_live_disabled: bool
    default_config_live_disabled: bool
    single_env_live_enable_forbidden: bool
    actual_soak_seconds: int
    tiny_allowlisted_exposure_lamports: int
    max_tiny_exposure_lamports: int
    protected_sol_reserve_lamports: int
    one_outstanding_submission: bool
    loss_stale_ambiguity_latches: bool
    manual_kill_switch: bool
    dual_human_approval_hash: str | None
    rollback_to_shadow_hash: str | None

    def __post_init__(self) -> None:
        if min(
            self.actual_soak_seconds,
            self.tiny_allowlisted_exposure_lamports,
            self.max_tiny_exposure_lamports,
            self.protected_sol_reserve_lamports,
        ) < 0:
            raise ValueError("canary numeric fields must be non-negative")


@dataclass(frozen=True, slots=True)
class ReleasePathEvidence:
    signer: SignerBoundaryEvidence
    authorization: AuthorizationEvidence
    submission: SubmissionLifecycleEvidence
    jito: JitoSafetyEvidence
    settlement: FinalizedSettlementEvidence
    release: HermeticReleaseEvidence
    sandbox: ProductionSandboxEvidence
    canary: ReviewedCanaryEvidence


@dataclass(frozen=True, slots=True)
class ReleaseFailure:
    reason: ReleaseFailureReason
    detail: str


@dataclass(frozen=True, slots=True)
class ReleaseGateReport:
    decision: ReleaseDecision
    failures: tuple[ReleaseFailure, ...]
    evidence_hash: str
    live_allowed: bool

    @property
    def approved(self) -> bool:
        return self.decision is ReleaseDecision.APPROVED


def evaluate_release_gate(
    evidence: ReleasePathEvidence,
    *,
    now_unix_ms: int,
    minimum_soak_seconds: int = MINIMUM_SOAK_SECONDS,
) -> ReleaseGateReport:
    if now_unix_ms <= 0:
        raise ValueError("now_unix_ms must be positive")
    failures: list[ReleaseFailure] = []
    _extend(failures, _check_signer(evidence.signer))
    _extend(failures, _check_authorization(evidence.authorization, now_unix_ms))
    _extend(failures, _check_submission(evidence.submission))
    _extend(failures, _check_jito(evidence.jito))
    _extend(failures, _check_settlement(evidence.settlement))
    _extend(failures, _check_release(evidence.release))
    _extend(failures, _check_sandbox(evidence.sandbox))
    _extend(failures, _check_canary(evidence.canary, minimum_soak_seconds))
    decision = ReleaseDecision.APPROVED if not failures else ReleaseDecision.BLOCKED
    return ReleaseGateReport(
        decision=decision,
        failures=tuple(failures),
        evidence_hash=_hash_dict(_plain(evidence)),
        live_allowed=decision is ReleaseDecision.APPROVED,
    )


def scan_forbidden_live_surface(source_text: str) -> tuple[str, ...]:
    patterns = {
        "Keypair": r"\bKeypair\b",
        "sendTransaction": r"\bsendTransaction\b",
        "skipPreflight": r"\bskipPreflight\b",
        "private_key": r"\bprivate[_-]?key\b",
        "secret_key": r"\bsecret[_-]?key\b",
        "live_control": r"\blive_control\b",
        "standalone_jito_tip": r"\bstandalone[_-]?jito[_-]?tip\b",
    }
    return tuple(
        name
        for name, pattern in patterns.items()
        if re.search(pattern, source_text, flags=re.IGNORECASE)
    )


def _check_signer(e: SignerBoundaryEvidence) -> tuple[ReleaseFailure, ...]:
    out: list[ReleaseFailure] = []
    if e.network_runtime_imports_keypair or e.network_runtime_has_private_key_bytes:
        out.append(
            _failure(
                ReleaseFailureReason.PRIVATE_KEY_IN_NETWORK,
                "network runtime can reach private key material",
            )
        )
    if e.signer_backend is SignerBackendKind.DEVELOPMENT_MEMORY:
        out.append(
            _failure(
                ReleaseFailureReason.UNSUPPORTED_SIGNER_BACKEND,
                "development signer is not canary-capable",
            )
        )
    if e.signer_has_general_network_access:
        out.append(
            _failure(
                ReleaseFailureReason.SIGNER_NOT_ISOLATED,
                "signer has general network access",
            )
        )
    for ok, detail in (
        (e.signer_parses_exact_v0_message, "signer must parse exact v0 message"),
        (
            e.signer_derives_payer_signers_programs_accounts,
            "signer must derive payer/signers/programs/accounts",
        ),
        (e.signer_verifies_policy_and_proof_hashes, "signer must verify policy/proof hashes"),
        (
            e.signer_checks_full_wire_limit,
            f"signer must enforce {FULL_TRANSACTION_WIRE_LIMIT_BYTES} byte full wire ceiling",
        ),
        (e.signer_returns_signature_only, "signer must return signature only"),
    ):
        if not ok:
            out.append(_failure(ReleaseFailureReason.SIGNER_NOT_ISOLATED, detail))
    return tuple(out)


def _check_authorization(
    e: AuthorizationEvidence,
    now_unix_ms: int,
) -> tuple[ReleaseFailure, ...]:
    out: list[ReleaseFailure] = []
    missing = sorted(_REQUIRED_AUTHORIZATION_BINDINGS - set(e.bindings))
    if missing:
        out.append(_failure(ReleaseFailureReason.AUTHORIZATION_INCOMPLETE, ",".join(missing)))
    for key, value in e.bindings.items():
        if key.endswith("_hash") or key in {"exact_message_hash", "nonce"}:
            if _looks_placeholder_hash(value):
                out.append(_failure(ReleaseFailureReason.PLACEHOLDER_HASH, key))
    if not e.durable:
        out.append(_failure(ReleaseFailureReason.AUTHORIZATION_NOT_DURABLE, "authorization is not durable"))
    if not e.authenticated:
        out.append(_failure(ReleaseFailureReason.AUTHORIZATION_INCOMPLETE, "authorization is not authenticated"))
    if e.caller_constructable_plain_dataclass:
        out.append(_failure(ReleaseFailureReason.PLAIN_CALLER_PERMIT, "plain caller permit"))
    if not e.one_time_nonce_persisted or e.expiry_unix_ms <= now_unix_ms:
        out.append(_failure(ReleaseFailureReason.AUTHORIZATION_REPLAYABLE, "nonce/expiry invalid"))
    return tuple(out)


def _check_submission(e: SubmissionLifecycleEvidence) -> tuple[ReleaseFailure, ...]:
    out: list[ReleaseFailure] = []
    if not e.durable_signing_intent or not e.durable_submission_intent:
        out.append(_failure(ReleaseFailureReason.AUTHORIZATION_NOT_DURABLE, "missing durable intent"))
    if not e.signed_payload_verified:
        out.append(_failure(ReleaseFailureReason.AUTHORIZATION_INCOMPLETE, "signed payload not verified"))
    if e.current_state is SubmissionState.UNKNOWN:
        out.append(_failure(ReleaseFailureReason.SUBMISSION_STATE_AMBIGUOUS, "unknown submission state"))
    if e.auto_resend_on_ambiguity:
        out.append(_failure(ReleaseFailureReason.AUTO_RESEND_ON_AMBIGUITY, "auto resend forbidden"))
    if not e.ambiguity_latch_enabled:
        out.append(_failure(ReleaseFailureReason.LATCH_MISSING, "ambiguity latch missing"))
    if e.indeterminate_outcome:
        out.append(_failure(ReleaseFailureReason.INDETERMINATE_OUTCOME, "freeze new submissions"))
    return tuple(out)


def _check_jito(e: JitoSafetyEvidence) -> tuple[ReleaseFailure, ...]:
    if not e.enabled:
        return ()
    out: list[ReleaseFailure] = []
    for ok, detail in (
        (e.one_atomic_transaction, "not one atomic transaction"),
        (e.tip_inside_same_transaction, "tip outside tx"),
        (e.exactly_one_tip, "tip count not exactly one"),
        (e.bundle_only_reviewed, "bundleOnly not reviewed"),
        (e.standalone_tip_forbidden, "standalone tip allowed"),
    ):
        if not ok:
            out.append(_failure(ReleaseFailureReason.JITO_UNSAFE, detail))
    for value, detail in (
        (e.current_tip_account_evidence_hash, "tip account evidence"),
        (e.uncle_unbundling_drill_hash, "uncle/unbundling drill"),
    ):
        if _looks_placeholder_hash(value or ""):
            out.append(_failure(ReleaseFailureReason.JITO_UNSAFE, detail))
    return tuple(out)


def _check_settlement(e: FinalizedSettlementEvidence) -> tuple[ReleaseFailure, ...]:
    out: list[ReleaseFailure] = []
    if not e.finalized or not e.get_transaction_max_supported_v0:
        out.append(
            _failure(
                ReleaseFailureReason.SETTLEMENT_NOT_FINALIZED,
                "finalized v0 getTransaction evidence missing",
            )
        )
    if not e.meta_err_is_none or e.conservative_net_lamports < 0:
        out.append(
            _failure(
                ReleaseFailureReason.SETTLEMENT_RECONCILIATION_MISSING,
                "settlement not reconciled",
            )
        )
    return tuple(out)


def _check_release(e: HermeticReleaseEvidence) -> tuple[ReleaseFailure, ...]:
    return tuple(
        _failure(ReleaseFailureReason.RELEASE_NOT_HERMETIC, detail)
        for ok, detail in (
            (e.github_actions_pinned_to_full_sha, "actions not pinned"),
            (e.docker_image_pinned_by_digest, "docker not digest-pinned"),
            (e.hashed_wheelhouse, "wheelhouse not hashed"),
            (e.offline_reproducible_build, "offline reproducible build missing"),
        )
        if not ok
    )


def _check_sandbox(e: ProductionSandboxEvidence) -> tuple[ReleaseFailure, ...]:
    return tuple(
        _failure(ReleaseFailureReason.SANDBOX_INCOMPLETE, detail)
        for ok, detail in (
            (e.read_only_root_fs, "read-only root fs"),
            (e.capability_drop, "capability drop"),
            (e.no_new_privileges, "no-new-privileges"),
            (e.seccomp_or_apparmor, "seccomp/AppArmor"),
            (e.cpu_memory_pid_fd_limits, "resource limits"),
            (e.egress_allowlist, "egress allowlist"),
            (e.signer_network_separation, "signer/network separation"),
        )
        if not ok
    )


def _check_canary(
    e: ReviewedCanaryEvidence,
    minimum_soak_seconds: int,
) -> tuple[ReleaseFailure, ...]:
    out: list[ReleaseFailure] = []
    if not e.default_package_live_disabled or not e.default_config_live_disabled:
        out.append(_failure(ReleaseFailureReason.LIVE_DEFAULT_ENABLED, "defaults must be live-disabled"))
    if not e.single_env_live_enable_forbidden:
        out.append(_failure(ReleaseFailureReason.SINGLE_ENV_ENABLES_LIVE, "single-env live enable forbidden"))
    if e.actual_soak_seconds < minimum_soak_seconds:
        out.append(_failure(ReleaseFailureReason.SOAK_INCOMPLETE, "72h soak incomplete"))
    if e.tiny_allowlisted_exposure_lamports > e.max_tiny_exposure_lamports or not e.one_outstanding_submission:
        out.append(_failure(ReleaseFailureReason.EXPOSURE_TOO_LARGE, "exposure/submission limit invalid"))
    if not e.loss_stale_ambiguity_latches:
        out.append(_failure(ReleaseFailureReason.LATCH_MISSING, "loss/stale/ambiguity latches missing"))
    if not e.manual_kill_switch:
        out.append(_failure(ReleaseFailureReason.LATCH_MISSING, "manual kill switch missing"))
    if e.mode is CanaryMode.REVIEWED_TINY_CANARY:
        if _looks_placeholder_hash(e.dual_human_approval_hash or ""):
            out.append(_failure(ReleaseFailureReason.OPERATOR_APPROVAL_MISSING, "dual approval missing"))
        if _looks_placeholder_hash(e.rollback_to_shadow_hash or ""):
            out.append(_failure(ReleaseFailureReason.OPERATOR_APPROVAL_MISSING, "rollback plan missing"))
    return tuple(out)


def _extend(target: list[ReleaseFailure], values: tuple[ReleaseFailure, ...]) -> None:
    target.extend(values)


def _failure(reason: ReleaseFailureReason, detail: str) -> ReleaseFailure:
    return ReleaseFailure(reason, detail)


def _plain(value: object) -> object:
    if isinstance(value, StrEnum):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return {k: _plain(v) for k, v in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(k): _plain(value[k]) for k in sorted(value, key=str)}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value


def _hash_dict(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _require_hash(value: str, field_name: str) -> None:
    if _looks_placeholder_hash(value):
        raise ValueError(f"{field_name} must be a non-placeholder hash")


def _looks_placeholder_hash(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in _PLACEHOLDER_HASHES or len(normalized) < 32:
        return True
    try:
        int(normalized, 16)
    except ValueError:
        return False
    return len(set(normalized)) == 1


__all__ = [
    "CanaryMode",
    "FULL_TRANSACTION_WIRE_LIMIT_BYTES",
    "FinalizedSettlementEvidence",
    "HermeticReleaseEvidence",
    "JitoSafetyEvidence",
    "MINIMUM_SOAK_SECONDS",
    "ProductionSandboxEvidence",
    "ReleaseDecision",
    "ReleaseFailure",
    "ReleaseFailureReason",
    "ReleaseGateReport",
    "ReleasePathEvidence",
    "ReviewedCanaryEvidence",
    "SignerBackendKind",
    "SignerBoundaryEvidence",
    "SubmissionLifecycleEvidence",
    "SubmissionState",
    "AuthorizationEvidence",
    "evaluate_release_gate",
    "scan_forbidden_live_surface",
]
