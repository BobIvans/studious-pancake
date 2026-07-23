"""MEGA-PR-03 canonical live-boundary convergence gate.

This checkpoint is intentionally offline and fail-closed. It converges the
existing signer, durable-intent, settlement, and canary proof surfaces onto one
canonical ownership map without importing a private-key loader, signer backend,
RPC/Jito sender, or live execution transport.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
import hashlib
import json
import re
from typing import Any

SCHEMA_VERSION = "mega-pr-03.live-canary-convergence.v1"
CHECKPOINT = "cp1-canonical-live-boundary"

CANONICAL_OWNER_BY_ROLE = {
    "signer_boundary": "src.live_boundary.pr202_isolated_signer_settlement",
    "authorization": "src.pr211_signer_outbox_finality_gate",
    "durable_submission_intent": (
        "isolated-signer-service/pr199-artifact"
    ),
    "finalized_settlement": "src.live_boundary.pr202_isolated_signer_settlement",
    "canary_governance": "src.mpr14_durable_canary_operator_control",
    "capital_latch": "src.mpr14_durable_canary_operator_control",
    "trusted_time_and_replay": "src.mpr16_trusted_time_archive_gate",
    "deployment_qualification": "src.mpr17_hermetic_deployment_cutover_gate",
    "realized_pnl": "src.live_boundary.pr202_isolated_signer_settlement",
}

REQUIRED_REVIEW_ONLY_SURFACES = (
    "src.pr199_live_boundary_canary_gate",
    "src.release_gate.mpr07_operations_promotion_gate",
)

REQUIRED_COMPATIBILITY_ALIASES = {
    "src.submission.pr202_isolated_signer_settlement": (
        "src.live_boundary.pr202_isolated_signer_settlement"
    ),
}

REQUIRED_SUBMISSION_CRASH_DRILLS = (
    "crash_before_send",
    "timeout_after_provider_acceptance",
    "crash_after_send_before_ack",
    "restart_with_unknown_outcome",
    "blockhash_expiry",
    "duplicate_submission_request",
    "jito_unbundling_or_uncle_leakage",
)

REQUIRED_CANARY_BINDINGS = (
    "release",
    "config",
    "wallet",
    "program_registry",
    "provider_registry",
    "message",
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/=-]{0,127}$")


@dataclass(frozen=True, slots=True)
class MegaPR03Report:
    """Deterministic CP1 result for MEGA-PR-03."""

    schema_version: str
    checkpoint: str
    accepted: bool
    blockers: tuple[str, ...]
    evidence_hash: str
    canonical_owner_hash: str
    bounded_canary_review_allowed: bool
    live_execution_allowed: bool
    unrestricted_live_allowed: bool
    automatic_scale_up_allowed: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def evaluate_mega_pr03_checkpoint(evidence: Mapping[str, Any]) -> MegaPR03Report:
    """Validate the first MEGA-PR-03 convergence checkpoint."""

    blockers: list[str] = []

    _require(
        evidence.get("schema_version") == SCHEMA_VERSION,
        blockers,
        "MEGA_PR03_SCHEMA_INVALID",
    )
    _require(
        evidence.get("checkpoint") == CHECKPOINT,
        blockers,
        "MEGA_PR03_CHECKPOINT_INVALID",
    )

    _check_mega_pr02_dependency(evidence.get("mega_pr02"), blockers)
    _check_authority(evidence.get("authority"), blockers)
    _check_signer_boundary(evidence.get("signer_boundary"), blockers)
    _check_submission(evidence.get("submission"), blockers)
    _check_settlement(evidence.get("settlement"), blockers)
    _check_canary(evidence.get("canary"), blockers)
    _check_capabilities(evidence.get("capabilities"), blockers)

    canonical_owner_hash = _sha256_json(
        {
            "domain": "studious-pancake/mega-pr-03/canonical-owners",
            "owners": CANONICAL_OWNER_BY_ROLE,
            "review_only": REQUIRED_REVIEW_ONLY_SURFACES,
            "compatibility_aliases": REQUIRED_COMPATIBILITY_ALIASES,
        }
    )
    evidence_hash = _sha256_json(
        {
            "domain": "studious-pancake/mega-pr-03/checkpoint",
            "schema_version": SCHEMA_VERSION,
            "checkpoint": CHECKPOINT,
            "evidence": evidence,
            "canonical_owner_hash": canonical_owner_hash,
        }
    )
    blockers_tuple = tuple(dict.fromkeys(blockers))
    accepted = not blockers_tuple
    return MegaPR03Report(
        schema_version=SCHEMA_VERSION,
        checkpoint=CHECKPOINT,
        accepted=accepted,
        blockers=blockers_tuple,
        evidence_hash=evidence_hash,
        canonical_owner_hash=canonical_owner_hash,
        bounded_canary_review_allowed=accepted,
        live_execution_allowed=False,
        unrestricted_live_allowed=False,
        automatic_scale_up_allowed=False,
    )


def _check_mega_pr02_dependency(value: object, blockers: list[str]) -> None:
    data = _mapping(value)
    _require(data is not None, blockers, "MEGA_PR02_EVIDENCE_MISSING")
    if data is None:
        return

    checks = (
        ("accepted", "MEGA_PR02_NOT_ACCEPTED"),
        ("paper_ready", "MEGA_PR02_NOT_PAPER_READY"),
        ("release_bound", "MEGA_PR02_NOT_RELEASE_BOUND"),
        ("independently_reviewed", "MEGA_PR02_NOT_INDEPENDENTLY_REVIEWED"),
        ("live_physically_disabled", "MEGA_PR02_LIVE_NOT_DISABLED"),
        ("non_synthetic_qualification", "MEGA_PR02_QUALIFICATION_SYNTHETIC"),
    )
    for key, reason in checks:
        _require(bool(data.get(key)), blockers, reason)

    for key in (
        "source_sha256",
        "wheel_sha256",
        "image_sha256",
        "config_sha256",
        "policy_sha256",
        "qualification_sha256",
    ):
        _require(
            _is_sha256(data.get(key)),
            blockers,
            f"MEGA_PR02_{key.upper()}_INVALID",
        )


def _check_authority(value: object, blockers: list[str]) -> None:
    data = _mapping(value)
    _require(data is not None, blockers, "LIVE_BOUNDARY_AUTHORITY_MISSING")
    if data is None:
        return

    owners = _mapping(data.get("owners"))
    _require(owners is not None, blockers, "LIVE_BOUNDARY_OWNERS_MISSING")
    if owners is not None:
        for role, expected_owner in CANONICAL_OWNER_BY_ROLE.items():
            _require(
                owners.get(role) == expected_owner,
                blockers,
                f"LIVE_BOUNDARY_OWNER_INVALID:{role}",
            )
        extra_roles = sorted(set(owners) - set(CANONICAL_OWNER_BY_ROLE))
        _require(not extra_roles, blockers, "LIVE_BOUNDARY_UNKNOWN_OWNER_ROLE")

    review_only = set(_string_tuple(data.get("review_only_surfaces")))
    _require(
        set(REQUIRED_REVIEW_ONLY_SURFACES).issubset(review_only),
        blockers,
        "LIVE_BOUNDARY_REVIEW_SURFACE_NOT_QUARANTINED",
    )

    aliases = _mapping(data.get("compatibility_aliases"))
    _require(aliases is not None, blockers, "LIVE_BOUNDARY_ALIASES_MISSING")
    if aliases is not None:
        for alias, target in REQUIRED_COMPATIBILITY_ALIASES.items():
            _require(
                aliases.get(alias) == target,
                blockers,
                f"LIVE_BOUNDARY_ALIAS_INVALID:{alias}",
            )

    _require(
        not bool(data.get("runtime_private_key_loader_present")),
        blockers,
        "RUNTIME_PRIVATE_KEY_LOADER_PRESENT",
    )
    _require(
        not bool(data.get("runtime_sender_present")),
        blockers,
        "RUNTIME_SENDER_PRESENT",
    )
    _require(
        bool(data.get("one_owner_per_role_enforced")),
        blockers,
        "LIVE_BOUNDARY_DUPLICATE_OWNER_ALLOWED",
    )


def _check_signer_boundary(value: object, blockers: list[str]) -> None:
    data = _mapping(value)
    _require(data is not None, blockers, "SIGNER_BOUNDARY_EVIDENCE_MISSING")
    if data is None:
        return

    required_true = {
        "separate_process": "SIGNER_NOT_SEPARATE_PROCESS",
        "separate_image": "SIGNER_NOT_SEPARATE_IMAGE",
        "narrow_authenticated_ipc": "SIGNER_IPC_NOT_AUTHENTICATED",
        "client_identity_bound": "SIGNER_CLIENT_IDENTITY_NOT_BOUND",
        "exact_message_hash_only": "SIGNER_ACCEPTS_MUTABLE_MESSAGE",
        "semantic_bounds_enforced": "SIGNER_BOUNDS_NOT_ENFORCED",
        "replay_nonce_persisted": "SIGNER_REPLAY_NONCE_NOT_PERSISTED",
        "request_size_bounded": "SIGNER_REQUEST_SIZE_UNBOUNDED",
        "request_deadline_bounded": "SIGNER_REQUEST_DEADLINE_UNBOUNDED",
        "compile_time_live_disabled": "SIGNER_COMPILE_GATE_NOT_DISABLED",
    }
    for key, reason in required_true.items():
        _require(bool(data.get(key)), blockers, reason)

    required_false = {
        "runtime_image_contains_key_loader": "RUNTIME_IMAGE_CONTAINS_KEY_LOADER",
        "signer_image_contains_strategy_logic": "SIGNER_IMAGE_CONTAINS_STRATEGY",
        "signer_accepts_provider_inputs": "SIGNER_ACCEPTS_PROVIDER_INPUTS",
        "raw_env_private_key_allowed": "SIGNER_RAW_ENV_KEY_ALLOWED",
        "arbitrary_message_signing_allowed": "SIGNER_ARBITRARY_SIGNING_ALLOWED",
    }
    for key, reason in required_false.items():
        _require(not bool(data.get(key)), blockers, reason)

    _require(
        data.get("key_authority") in {"hsm", "kms", "secret_manager"},
        blockers,
        "SIGNER_KEY_AUTHORITY_INVALID",
    )
    _require(
        _is_sha256(data.get("signer_image_sha256")),
        blockers,
        "SIGNER_IMAGE_HASH_INVALID",
    )
    _require(
        _is_sha256(data.get("ipc_policy_sha256")),
        blockers,
        "SIGNER_IPC_POLICY_HASH_INVALID",
    )


def _check_submission(value: object, blockers: list[str]) -> None:
    data = _mapping(value)
    _require(data is not None, blockers, "SUBMISSION_EVIDENCE_MISSING")
    if data is None:
        return

    required_true = {
        "durable_intent_before_network": "SUBMISSION_INTENT_NOT_DURABLE_FIRST",
        "one_selected_transport": "SUBMISSION_TRANSPORT_NOT_UNIQUE",
        "ack_not_economic_success": "SUBMISSION_ACK_COUNTS_AS_SUCCESS",
        "processed_confirmed_not_success": "NON_FINAL_STATUS_COUNTS_AS_SUCCESS",
        "no_blind_retry": "SUBMISSION_BLIND_RETRY_ALLOWED",
        "blockheight_rechecked_before_send": "SUBMISSION_BLOCKHEIGHT_NOT_RECHECKED",
        "rate_limits_enforced": "SUBMISSION_RATE_LIMIT_MISSING",
        "unbundling_leakage_policy": "JITO_UNBUNDLING_POLICY_MISSING",
        "receipt_durable_and_signed": "SUBMISSION_RECEIPT_NOT_DURABLE_SIGNED",
        "unknown_state_persisted": "SUBMISSION_UNKNOWN_NOT_PERSISTED",
    }
    for key, reason in required_true.items():
        _require(bool(data.get(key)), blockers, reason)

    drills = set(_string_tuple(data.get("crash_drills")))
    _require(
        set(REQUIRED_SUBMISSION_CRASH_DRILLS).issubset(drills),
        blockers,
        "SUBMISSION_CRASH_MATRIX_INCOMPLETE",
    )
    _require(
        data.get("retry_policy") in {"no_retry", "status_search_then_operator_review"},
        blockers,
        "SUBMISSION_RETRY_POLICY_UNSAFE",
    )


def _check_settlement(value: object, blockers: list[str]) -> None:
    data = _mapping(value)
    _require(data is not None, blockers, "SETTLEMENT_EVIDENCE_MISSING")
    if data is None:
        return

    required_true = {
        "get_transaction_materialized": "FINALIZED_TRANSACTION_NOT_MATERIALIZED",
        "v0_supported": "FINALIZED_V0_NOT_SUPPORTED",
        "intent_message_hash_bound": "FINALIZED_MESSAGE_NOT_BOUND",
        "payer_lamport_delta_bound": "FINALIZED_PAYER_DELTA_NOT_BOUND",
        "token_deltas_bound": "FINALIZED_TOKEN_DELTAS_NOT_BOUND",
        "inner_instructions_bound": "FINALIZED_INNER_INSTRUCTIONS_NOT_BOUND",
        "fee_tip_rent_accounted": "FINALIZED_COST_ACCOUNTING_INCOMPLETE",
        "borrow_repayment_verified": "FINALIZED_REPAYMENT_NOT_VERIFIED",
        "unknown_holds_capital": "UNKNOWN_OUTCOME_RELEASES_CAPITAL",
        "fork_reorg_rpc_disagreement_blocks": "FINALITY_DISAGREEMENT_NOT_BLOCKING",
        "external_wallet_activity_blocks": "EXTERNAL_WALLET_ACTIVITY_NOT_BLOCKING",
        "realized_pnl_only": "CANARY_METRICS_NOT_REALIZED_PNL",
        "bounded_recovery": "FINALITY_RECOVERY_UNBOUNDED",
        "restart_idempotent": "FINALITY_RESTART_NOT_IDEMPOTENT",
    }
    for key, reason in required_true.items():
        _require(bool(data.get(key)), blockers, reason)

    _require(
        data.get("commitment") == "finalized",
        blockers,
        "FINALITY_COMMITMENT_NOT_FINALIZED",
    )
    _require(
        data.get("terminal_states")
        == ("finalized_success", "finalized_failure", "expired", "unknown_locked"),
        blockers,
        "FINALITY_TERMINAL_STATE_SET_INVALID",
    )


def _check_canary(value: object, blockers: list[str]) -> None:
    data = _mapping(value)
    _require(data is not None, blockers, "CANARY_EVIDENCE_MISSING")
    if data is None:
        return

    required_true = {
        "permit_signed": "CANARY_PERMIT_NOT_SIGNED",
        "permit_one_time": "CANARY_PERMIT_NOT_ONE_TIME",
        "permit_expiring": "CANARY_PERMIT_NOT_EXPIRING",
        "latch_persistent_across_restart": "CANARY_LATCH_NOT_PERSISTENT",
        "unknown_closes_latch": "CANARY_UNKNOWN_DOES_NOT_CLOSE_LATCH",
        "provider_drift_closes_latch": "CANARY_PROVIDER_DRIFT_DOES_NOT_CLOSE_LATCH",
        "reconciliation_lag_closes_latch": (
            "CANARY_RECONCILIATION_LAG_DOES_NOT_CLOSE_LATCH"
        ),
        "post_run_evidence_signed": "CANARY_POST_RUN_EVIDENCE_NOT_SIGNED",
        "manual_go_no_go_required": "CANARY_MANUAL_GO_NO_GO_MISSING",
    }
    for key, reason in required_true.items():
        _require(bool(data.get(key)), blockers, reason)

    bindings = set(_string_tuple(data.get("permit_bindings")))
    _require(
        set(REQUIRED_CANARY_BINDINGS).issubset(bindings),
        blockers,
        "CANARY_PERMIT_BINDING_INCOMPLETE",
    )

    reviewers = _string_tuple(data.get("reviewer_ids"))
    _require(len(set(reviewers)) >= 2, blockers, "CANARY_TWO_PERSON_APPROVAL_MISSING")
    proposer_id = data.get("proposer_id")
    _require(
        _safe_id(proposer_id) and proposer_id not in set(reviewers),
        blockers,
        "CANARY_SELF_APPROVAL_FORBIDDEN",
    )

    max_capital = _positive_int_value(data.get("max_capital_lamports"))
    wallet_capital = _positive_int_value(data.get("wallet_capital_lamports"))
    max_daily_loss = _positive_int_value(data.get("max_daily_loss_lamports"))
    max_fee_tip = _positive_int_value(data.get("max_fee_tip_lamports"))
    max_transactions = _positive_int_value(data.get("max_transactions"))
    max_in_flight = _positive_int_value(data.get("max_in_flight"))
    max_slippage_bps = _positive_int_value(data.get("max_slippage_bps"))

    _require(max_capital is not None, blockers, "CANARY_CAPITAL_BOUND_INVALID")
    _require(wallet_capital is not None, blockers, "CANARY_WALLET_CAPITAL_INVALID")
    if max_capital is not None and wallet_capital is not None:
        _require(
            max_capital <= wallet_capital,
            blockers,
            "CANARY_CAPITAL_EXCEEDS_WALLET",
        )
    if max_daily_loss is None or max_capital is None:
        _require(False, blockers, "CANARY_DAILY_LOSS_BOUND_INVALID")
    else:
        _require(
            max_daily_loss <= max_capital,
            blockers,
            "CANARY_DAILY_LOSS_EXCEEDS_CAPITAL",
        )
    if max_fee_tip is None or max_capital is None:
        _require(False, blockers, "CANARY_FEE_TIP_BOUND_INVALID")
    else:
        _require(
            max_fee_tip <= max_capital,
            blockers,
            "CANARY_FEE_TIP_EXCEEDS_CAPITAL",
        )
    _require(
        max_transactions is not None and max_transactions <= 10,
        blockers,
        "CANARY_TRANSACTION_COUNT_UNBOUNDED",
    )
    _require(max_in_flight == 1, blockers, "CANARY_IN_FLIGHT_MUST_BE_ONE")
    _require(
        max_slippage_bps is not None and max_slippage_bps <= 100,
        blockers,
        "CANARY_SLIPPAGE_BOUND_UNSAFE",
    )
    _require(
        not bool(data.get("automatic_scale_up")),
        blockers,
        "CANARY_AUTOMATIC_SCALE_UP_FORBIDDEN",
    )
    _require(
        not bool(data.get("unrestricted_live")),
        blockers,
        "CANARY_UNRESTRICTED_LIVE_FORBIDDEN",
    )


def _check_capabilities(value: object, blockers: list[str]) -> None:
    data = _mapping(value)
    _require(data is not None, blockers, "CAPABILITY_EVIDENCE_MISSING")
    if data is None:
        return

    forbidden = {
        "live_execution_enabled": "LIVE_EXECUTION_MUST_REMAIN_DISABLED",
        "unrestricted_live_enabled": "UNRESTRICTED_LIVE_MUST_REMAIN_DISABLED",
        "automatic_scale_up_enabled": "AUTOMATIC_SCALE_UP_MUST_REMAIN_DISABLED",
        "runtime_private_key_access": "RUNTIME_PRIVATE_KEY_ACCESS_FORBIDDEN",
        "runtime_sender_access": "RUNTIME_SENDER_ACCESS_FORBIDDEN",
    }
    for key, reason in forbidden.items():
        _require(not bool(data.get(key)), blockers, reason)


def _mapping(value: object) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item)


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and bool(_SHA256_RE.fullmatch(value))


def _safe_id(value: object) -> bool:
    return isinstance(value, str) and bool(_SAFE_ID_RE.fullmatch(value))


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _positive_int_value(value: object) -> int | None:
    return value if _positive_int(value) else None


def _require(condition: bool, blockers: list[str], reason: str) -> None:
    if not condition:
        blockers.append(reason)


def _sha256_json(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
