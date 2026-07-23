"""MPR-02 provider/protocol conformance and rooted data-plane gate.

Offline, sender-free review contract.  It validates redacted, content-addressed
provider evidence without calling providers, reading secrets, signing, sending or
enabling live execution.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
import math
import re
from typing import Any, Iterable, Mapping, Sequence


SCHEMA_VERSION = "mpr-02.provider-protocol-rooted-data-plane.v1"

REQUIRED_DEBT_IDS: tuple[str, ...] = (
    "data.rpc-rooted-quorum",
    "data.oracle-slot-coherence",
    "external.solana-v0-rpc",
    "external.jupiter-swap-v2",
    "external.helius-webhook-auth",
    "external.marginfi-v2",
    "external.kamino-klend",
    "lending.kamino-supported-combinations",
    "external.okx-signed-discovery",
    "external.openocean-whitelist-discovery",
    "external.odos-immutable-transaction",
    "evidence.provider-drift-probes",
)

DISCOVERY_PROVIDERS: frozenset[str] = frozenset(("okx", "openocean", "odos"))
_SHA = re.compile(r"^[0-9a-f]{64}$")
_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/=-]{0,159}$")
_SECRET_HINTS = ("secret", "token", "bearer", "private", "apikey", "api_key", "rpc_key")


class MPR02State(StrEnum):
    READY_FOR_PROVIDER_PROTOCOL_REVIEW = "ready_for_provider_protocol_review"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    label: str
    sha256: str
    path: str
    redacted: bool = True


@dataclass(frozen=True, slots=True)
class SolanaV0RPCFinalityEvidence:
    exact_v0_message_simulation_fixture: bool
    get_fee_for_message_fixture: bool
    latest_blockhash_lifetime_fixture: bool
    address_lookup_table_provenance: bool
    get_transaction_versioned_fixture: bool
    finalized_balance_and_token_evidence: bool
    rooted_quorum_proven: bool
    oracle_slot_coherence_proven: bool
    endpoint_identity_bound_to_observation_hash: bool
    raw_request_response_hash_bound: bool
    finalized_commitment_only_for_settlement: bool
    redacted_stable_ci_fixtures: bool


@dataclass(frozen=True, slots=True)
class JupiterV2BuildEvidence:
    v2_build_only_execution_composable_path: bool
    v1_execution_claims_disabled: bool
    schema_validation: bool
    instruction_group_validation: bool
    alt_mapping_validation: bool
    blockhash_metadata_validation: bool
    raw_instruction_hash_bound: bool
    canonical_transaction_proof_compatible: bool
    credentialed_refresh_redacted: bool


@dataclass(frozen=True, slots=True)
class MarginFiV2ConformanceEvidence:
    status: str
    canonical_idl_layout_artifact: bool
    deployed_program_and_group_identity: bool
    sdk_account_vectors: bool
    sdk_instruction_vectors: bool
    read_only_mainnet_rpc_evidence: bool
    flashloan_borrow_repay_meta_proof: bool
    token_2022_and_token_program_handling: bool
    human_review_stamp: bool
    product_capability_promoted: bool = False


@dataclass(frozen=True, slots=True)
class KaminoKLendAdmissionEvidence:
    status: str
    supported_combinations_from_reviewed_markets: bool
    market_reserve_asset_provenance: bool
    no_guessed_market_or_reserve_ids: bool
    disabled_reason_present: bool
    product_capability_promoted: bool = False


@dataclass(frozen=True, slots=True)
class HeliusIngressEvidence:
    auth_header_validation: bool
    replay_dedup: bool
    gap_recovery: bool
    durable_handoff: bool
    rate_backpressure: bool
    lineage_tags_recorded_vs_credentialed: bool
    webhook_secret_not_committed: bool


@dataclass(frozen=True, slots=True)
class DiscoveryOnlyBoundaries:
    okx_discovery_only: bool
    openocean_discovery_only: bool
    odos_discovery_only: bool
    odos_immutable_transaction_marked_incompatible: bool
    no_discovery_provider_used_for_execution_composition: bool
    execution_provider_allowlist: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProviderDriftProbeEvidence:
    committed_fixture_validation_in_ci: bool
    manual_credentialed_refresh_command: bool
    refresh_never_commits_secrets: bool
    redaction_policy_hash: str
    drift_report_hash_bound: bool
    schema_regression_tests: bool


@dataclass(frozen=True, slots=True)
class MPR02Evidence:
    schema_version: str
    covered_debt_ids: tuple[str, ...]
    solana_rpc: SolanaV0RPCFinalityEvidence
    jupiter: JupiterV2BuildEvidence
    marginfi: MarginFiV2ConformanceEvidence
    kamino: KaminoKLendAdmissionEvidence
    helius: HeliusIngressEvidence
    discovery_boundaries: DiscoveryOnlyBoundaries
    drift_probes: ProviderDriftProbeEvidence
    evidence_refs: tuple[EvidenceRef, ...]
    operational_paper_ready_requested: bool = False
    live_execution_requested: bool = False
    sender_requested: bool = False
    secrets_committed: bool = False


@dataclass(frozen=True, slots=True)
class MPR02Violation:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class MPR02Report:
    schema_version: str
    state: MPR02State
    blockers: tuple[MPR02Violation, ...]
    covered_debt_ids: tuple[str, ...]
    evidence_hash: str
    provider_protocol_review_allowed: bool
    operational_paper_ready_allowed: bool
    live_execution_allowed: bool
    sender_allowed: bool


def evaluate_mpr02_evidence(evidence: MPR02Evidence) -> MPR02Report:
    blockers: list[MPR02Violation] = []
    if evidence.schema_version != SCHEMA_VERSION:
        _add(blockers, "MPR02_SCHEMA_VERSION", f"schema_version must be {SCHEMA_VERSION}")
    _covered_debt(evidence.covered_debt_ids, blockers)
    _evidence_refs(evidence.evidence_refs, blockers)
    _require_flags(blockers, "SOLANA", _bools(evidence.solana_rpc))
    _require_flags(blockers, "JUPITER", _bools(evidence.jupiter))
    _marginfi(evidence.marginfi, blockers)
    _kamino(evidence.kamino, blockers)
    _require_flags(blockers, "HELIUS", _bools(evidence.helius))
    _discovery(evidence.discovery_boundaries, blockers)
    _drift(evidence.drift_probes, blockers)
    _capability_requests(evidence, blockers)

    unique = tuple(_dedupe(blockers))
    ready = not unique
    return MPR02Report(
        schema_version=SCHEMA_VERSION,
        state=MPR02State.READY_FOR_PROVIDER_PROTOCOL_REVIEW if ready else MPR02State.BLOCKED,
        blockers=unique,
        covered_debt_ids=tuple(evidence.covered_debt_ids),
        evidence_hash=_stable_hash(evidence),
        provider_protocol_review_allowed=ready,
        operational_paper_ready_allowed=False,
        live_execution_allowed=False,
        sender_allowed=False,
    )


def report_to_dict(report: MPR02Report) -> dict[str, Any]:
    return {
        "schema_version": report.schema_version,
        "state": report.state.value,
        "blockers": [asdict(blocker) for blocker in report.blockers],
        "covered_debt_ids": list(report.covered_debt_ids),
        "evidence_hash": report.evidence_hash,
        "provider_protocol_review_allowed": report.provider_protocol_review_allowed,
        "operational_paper_ready_allowed": report.operational_paper_ready_allowed,
        "live_execution_allowed": report.live_execution_allowed,
        "sender_allowed": report.sender_allowed,
    }


def _covered_debt(items: Sequence[str], blockers: list[MPR02Violation]) -> None:
    missing = [item for item in REQUIRED_DEBT_IDS if item not in items]
    extra = [item for item in items if item not in REQUIRED_DEBT_IDS]
    if missing:
        _add(blockers, "MPR02_MISSING_DEBT_COVERAGE", f"missing debt ids: {missing}")
    if extra:
        _add(blockers, "MPR02_UNKNOWN_DEBT_COVERAGE", f"unknown debt ids: {extra}")
    if len(set(items)) != len(tuple(items)):
        _add(blockers, "MPR02_DUPLICATE_DEBT_COVERAGE", "debt coverage ids must be unique")


def _evidence_refs(refs: Sequence[EvidenceRef], blockers: list[MPR02Violation]) -> None:
    if len(refs) < 7:
        _add(blockers, "MPR02_INCOMPLETE_EVIDENCE_SET", "at least seven redacted protocol artifacts are required")
    labels: set[str] = set()
    for ref in refs:
        if ref.label in labels:
            _add(blockers, "MPR02_DUPLICATE_EVIDENCE_LABEL", f"duplicate label: {ref.label}")
        labels.add(ref.label)
        if not _safe(ref.label):
            _add(blockers, "MPR02_BAD_EVIDENCE_LABEL", f"unsafe label: {ref.label!r}")
        if not _sha(ref.sha256) or ref.sha256 == "0" * 64:
            _add(blockers, "MPR02_BAD_EVIDENCE_DIGEST", f"bad digest for {ref.label}")
        if not ref.path or ref.path.startswith("/") or ".." in ref.path.split("/"):
            _add(blockers, "MPR02_BAD_EVIDENCE_PATH", f"bad path for {ref.label}")
        if not ref.redacted:
            _add(blockers, "MPR02_UNREDACTED_EVIDENCE", f"unredacted evidence: {ref.label}")
        lowered = f"{ref.label}/{ref.path}".lower()
        if any(hint in lowered for hint in _SECRET_HINTS):
            _add(blockers, "MPR02_SECRET_LIKE_EVIDENCE_REF", f"secret-like evidence ref: {ref.label}")


def _marginfi(m: MarginFiV2ConformanceEvidence, blockers: list[MPR02Violation]) -> None:
    if m.status not in {"fixture_only_blocked", "conformance_ready"}:
        _add(blockers, "MPR02_MARGINFI_BAD_STATUS", "MarginFi must be fixture_only_blocked or conformance_ready")
    complete = all(value for key, value in _bools(m).items() if key != "product_capability_promoted")
    if m.status == "conformance_ready" and not complete:
        _add(blockers, "MPR02_MARGINFI_INCOMPLETE_CONFORMANCE", "MarginFi conformance-ready requires IDL/SDK/RPC/flashloan/Token-2022/human-review evidence")
    if m.status == "fixture_only_blocked" and m.product_capability_promoted:
        _add(blockers, "MPR02_MARGINFI_FIXTURE_PROMOTED", "fixture-only MarginFi must not be promoted")


def _kamino(k: KaminoKLendAdmissionEvidence, blockers: list[MPR02Violation]) -> None:
    if k.status not in {"disabled_fail_closed", "conformance_ready"}:
        _add(blockers, "MPR02_KAMINO_BAD_STATUS", "Kamino must be disabled_fail_closed or conformance_ready")
    ready = (
        k.supported_combinations_from_reviewed_markets
        and k.market_reserve_asset_provenance
        and k.no_guessed_market_or_reserve_ids
    )
    if k.status == "conformance_ready" and not ready:
        _add(blockers, "MPR02_KAMINO_UNPROVEN_COMBINATIONS", "Kamino requires reviewed market/reserve/asset provenance")
    if k.status == "disabled_fail_closed" and not k.disabled_reason_present:
        _add(blockers, "MPR02_KAMINO_DISABLED_REASON_MISSING", "disabled Kamino requires explicit fail-closed reason")
    if k.status == "disabled_fail_closed" and k.product_capability_promoted:
        _add(blockers, "MPR02_KAMINO_DISABLED_PROMOTED", "disabled Kamino must not be promoted")
    if not k.no_guessed_market_or_reserve_ids:
        _add(blockers, "MPR02_KAMINO_GUESSED_IDS", "guessed Kamino IDs are forbidden")


def _discovery(d: DiscoveryOnlyBoundaries, blockers: list[MPR02Violation]) -> None:
    flags = _bools(d)
    allowlist = flags.pop("execution_provider_allowlist")
    _require_flags(blockers, "DISCOVERY", flags)
    offenders = [provider for provider in allowlist if provider.lower() in DISCOVERY_PROVIDERS]
    if offenders:
        _add(blockers, "MPR02_DISCOVERY_EXECUTION_ALLOWLISTED", f"discovery providers cannot execute: {offenders}")


def _drift(d: ProviderDriftProbeEvidence, blockers: list[MPR02Violation]) -> None:
    flags = _bools(d)
    redaction_hash = flags.pop("redaction_policy_hash")
    _require_flags(blockers, "DRIFT", flags)
    if not _sha(redaction_hash):
        _add(blockers, "MPR02_DRIFT_REDACTION_POLICY_HASH_BAD", "redaction policy hash must be sha256 hex")


def _capability_requests(evidence: MPR02Evidence, blockers: list[MPR02Violation]) -> None:
    if evidence.operational_paper_ready_requested:
        _add(blockers, "MPR02_PAPER_READY_PROMOTION_FORBIDDEN", "MPR-02 cannot promote operational paper-ready")
    if evidence.live_execution_requested:
        _add(blockers, "MPR02_LIVE_EXECUTION_FORBIDDEN", "MPR-02 must not enable live")
    if evidence.sender_requested:
        _add(blockers, "MPR02_SENDER_FORBIDDEN", "MPR-02 must not enable sender/submission")
    if evidence.secrets_committed:
        _add(blockers, "MPR02_SECRETS_COMMITTED", "provider secrets must not be committed")


def _require_flags(blockers: list[MPR02Violation], prefix: str, flags: Mapping[str, Any]) -> None:
    for field, value in flags.items():
        if isinstance(value, bool) and not value:
            _add(blockers, f"MPR02_{prefix}_{field.upper()}_MISSING", field.replace("_", " "))


def _bools(item: object) -> dict[str, Any]:
    return asdict(item)


def _dedupe(items: Iterable[MPR02Violation]) -> list[MPR02Violation]:
    seen: set[tuple[str, str]] = set()
    out: list[MPR02Violation] = []
    for item in items:
        key = (item.code, item.message)
        if key not in seen:
            seen.add(key)
            out.append(item)
    return sorted(out, key=lambda item: item.code)


def _add(blockers: list[MPR02Violation], code: str, message: str) -> None:
    blockers.append(MPR02Violation(code, message))


def _safe(value: str) -> bool:
    return bool(_SAFE.fullmatch(value))


def _sha(value: str) -> bool:
    return bool(_SHA.fullmatch(value))


def _normalize(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return {key: _normalize(val) for key, val in asdict(value).items()}
    if isinstance(value, tuple):
        return [_normalize(item) for item in value]
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _normalize(value[key]) for key in sorted(value)}
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite float cannot be hashed")
    return value


def _stable_hash(value: Any) -> str:
    payload = json.dumps(_normalize(value), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()
