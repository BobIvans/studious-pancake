"""MPR-02 V6 protocol correctness gate.

Offline, sender-free validator for the V6 MEGA-PR-02 protocol-correctness
additions. It does not call providers, read secrets, construct transactions,
sign, submit, or enable live execution.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = "mpr-02.v6.protocol-correctness-gate.v1"
OFFICIAL_TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
OFFICIAL_TOKEN_2022_PROGRAM_ID = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
OFFICIAL_ASSOCIATED_TOKEN_PROGRAM_ID = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
REQUIRED_FINDINGS: tuple[str, ...] = (
    "IMPL-81", "IMPL-82", "IMPL-83", "IMPL-84", "IMPL-87", "IMPL-88",
    "IMPL-89", "IMPL-90", "IMPL-91", "IMPL-92", "IMPL-93", "IMPL-95",
)
_BASE58_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SHA256_URI_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_SAFE_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/=-]{0,127}$")
U64_MAX = 2**64 - 1


class MPR02V6State(StrEnum):
    READY_FOR_PHYSICAL_PROTOCOL_CUTOVER = "ready_for_physical_protocol_cutover"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class MPR02V6Violation:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class ChainIdentityRegistryEvidence:
    registry_generation: int
    genesis_hash: str
    registry_artifact_sha256: str
    token_program_id: str
    token_2022_program_id: str
    associated_token_program_id: str
    independent_golden_vectors: bool
    expected_ids_not_imported_from_modules_under_test: bool


@dataclass(frozen=True, slots=True)
class JupiterV2BuildRequest:
    input_mint: str
    output_mint: str
    amount: int
    taker: str
    slippage_bps: int
    dexes: tuple[str, ...] = ()
    exclude_dexes: tuple[str, ...] = ()
    max_accounts: int = 64
    blockhash_slots_to_expiry: int = 150
    swap_mode: str | None = None


@dataclass(frozen=True, slots=True)
class RoutePlanSegment:
    bps: int
    input_mint: str
    output_mint: str
    in_amount: int
    out_amount: int
    amm_key: str
    program_id: str
    label: str
    swap_info: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class JupiterV2BuildResponse:
    route_plan: tuple[RoutePlanSegment, ...]
    top_level_input_mint: str
    top_level_output_mint: str
    last_valid_block_height: int
    current_rooted_block_height: int
    remaining_height_margin: int
    blockhash_metadata_sha256: str


@dataclass(frozen=True, slots=True)
class MarginFiTokenAccountEvidence:
    account_pubkey: str
    token_program_id: str
    owner_program_id: str
    mint: str
    expected_mint: str
    authority: str
    expected_authority: str
    raw_account_sha256: str
    rooted_slot: int
    frozen: bool
    delegate_present: bool
    native_lamports_present: bool
    included_in_final_instruction_accounts: bool


@dataclass(frozen=True, slots=True)
class Token2022RentEvidence:
    token_program_id: str
    base_account_size: int
    extension_sizes: tuple[int, ...]
    rent_exempt_lamports: int
    rent_context_slot: int
    rent_response_sha256: str
    final_create_account_instruction_sha256: str


@dataclass(frozen=True, slots=True)
class CABundleEvidence:
    expected_sha256: str
    reviewed_bytes_sha256: str
    ssl_loaded_bytes_sha256: str
    private_copy_inode_sha256: str
    deployment_image_digest: str
    check_then_reopen_path: bool


@dataclass(frozen=True, slots=True)
class MPR02V6Evidence:
    schema_version: str
    covered_findings: tuple[str, ...]
    chain_registry: ChainIdentityRegistryEvidence
    jupiter_request: JupiterV2BuildRequest
    jupiter_response: JupiterV2BuildResponse
    marginfi_accounts: tuple[MarginFiTokenAccountEvidence, ...]
    token2022_rent: Token2022RentEvidence
    ca_bundle: CABundleEvidence
    operational_paper_ready_requested: bool = False
    live_execution_requested: bool = False
    sender_requested: bool = False


@dataclass(frozen=True, slots=True)
class MPR02V6Report:
    schema_version: str
    state: MPR02V6State
    blockers: tuple[MPR02V6Violation, ...]
    evidence_hash: str
    covered_findings: tuple[str, ...]
    protocol_correctness_review_allowed: bool
    operational_paper_ready_allowed: bool
    live_execution_allowed: bool
    sender_allowed: bool


def evaluate_mpr02_v6_protocol_correctness(evidence: MPR02V6Evidence) -> MPR02V6Report:
    blockers: list[MPR02V6Violation] = []
    _schema(evidence, blockers)
    _findings(evidence.covered_findings, blockers)
    _chain_registry(evidence.chain_registry, blockers)
    _jupiter_request(evidence.jupiter_request, blockers)
    _jupiter_response(evidence.jupiter_response, blockers)
    _marginfi_accounts(evidence.marginfi_accounts, blockers)
    _token2022_rent(evidence.token2022_rent, blockers)
    _ca_bundle(evidence.ca_bundle, blockers)
    _capability_requests(evidence, blockers)
    unique = tuple(_dedupe(blockers))
    ready = not unique
    return MPR02V6Report(
        schema_version=SCHEMA_VERSION,
        state=(MPR02V6State.READY_FOR_PHYSICAL_PROTOCOL_CUTOVER if ready else MPR02V6State.BLOCKED),
        blockers=unique,
        evidence_hash=_stable_hash(evidence),
        covered_findings=tuple(evidence.covered_findings),
        protocol_correctness_review_allowed=ready,
        operational_paper_ready_allowed=False,
        live_execution_allowed=False,
        sender_allowed=False,
    )


def _schema(evidence: MPR02V6Evidence, blockers: list[MPR02V6Violation]) -> None:
    if evidence.schema_version != SCHEMA_VERSION:
        _add(blockers, "MPR02_V6_SCHEMA_MISMATCH", "evidence schema version is not current")


def _findings(items: Sequence[str], blockers: list[MPR02V6Violation]) -> None:
    missing = [finding for finding in REQUIRED_FINDINGS if finding not in items]
    if missing:
        _add(blockers, "MPR02_V6_MISSING_FINDINGS", f"missing V6 findings: {missing}")
    if len(set(items)) != len(tuple(items)):
        _add(blockers, "MPR02_V6_DUPLICATE_FINDINGS", "covered findings must be unique")


def _chain_registry(registry: ChainIdentityRegistryEvidence, blockers: list[MPR02V6Violation]) -> None:
    if registry.registry_generation < 1:
        _add(blockers, "MPR02_V6_BAD_REGISTRY_GENERATION", "registry generation must be positive")
    _require_hash(blockers, "MPR02_V6_BAD_GENESIS_HASH", genesis_hash=registry.genesis_hash)
    _require_hash(blockers, "MPR02_V6_BAD_REGISTRY_HASH", registry_artifact_sha256=registry.registry_artifact_sha256)
    expected = {
        "token_program_id": OFFICIAL_TOKEN_PROGRAM_ID,
        "token_2022_program_id": OFFICIAL_TOKEN_2022_PROGRAM_ID,
        "associated_token_program_id": OFFICIAL_ASSOCIATED_TOKEN_PROGRAM_ID,
    }
    actual = {
        "token_program_id": registry.token_program_id,
        "token_2022_program_id": registry.token_2022_program_id,
        "associated_token_program_id": registry.associated_token_program_id,
    }
    for field_name, expected_value in expected.items():
        actual_value = actual[field_name]
        if actual_value != expected_value:
            _add(blockers, "MPR02_V6_NON_CANONICAL_PROGRAM_ID", f"{field_name} must be {expected_value}, got {actual_value}")
        elif not _pubkey(actual_value):
            _add(blockers, "MPR02_V6_BAD_PROGRAM_PUBKEY", f"{field_name} is not valid base58")
    if not registry.independent_golden_vectors:
        _add(blockers, "MPR02_V6_MISSING_OFFICIAL_GOLDEN_VECTORS", "official ID golden vectors required")
    if not registry.expected_ids_not_imported_from_modules_under_test:
        _add(blockers, "MPR02_V6_SELF_CERTIFYING_PROGRAM_IDS", "tests must not import expected IDs from modules under test")


def _jupiter_request(request: JupiterV2BuildRequest, blockers: list[MPR02V6Violation]) -> None:
    for name, value in (("input_mint", request.input_mint), ("output_mint", request.output_mint), ("taker", request.taker)):
        if not _pubkey(value):
            _add(blockers, "MPR02_V6_INVALID_JUPITER_PUBKEY", f"{name} is not a Solana pubkey")
    if request.input_mint == request.output_mint:
        _add(blockers, "MPR02_V6_JUPITER_MINTS_NOT_DISTINCT", "input/output mint must differ")
    if not _u64_positive(request.amount):
        _add(blockers, "MPR02_V6_BAD_JUPITER_AMOUNT", "amount must be positive u64")
    if not isinstance(request.slippage_bps, int) or request.slippage_bps < 0 or request.slippage_bps > 10_000:
        _add(blockers, "MPR02_V6_BAD_SLIPPAGE_BPS", "slippage_bps must be in 0..10000")
    if request.dexes and request.exclude_dexes:
        _add(blockers, "MPR02_V6_CONFLICTING_DEX_FILTERS", "dexes and excludeDexes are mutually exclusive")
    for filter_name, labels in (("dexes", request.dexes), ("exclude_dexes", request.exclude_dexes)):
        if len(set(labels)) != len(labels):
            _add(blockers, "MPR02_V6_DUPLICATE_DEX_LABEL", f"{filter_name} contains duplicate labels")
        for label in labels:
            if not _safe_label(label):
                _add(blockers, "MPR02_V6_BAD_DEX_LABEL", f"{filter_name} label is invalid: {label!r}")
    if request.max_accounts < 1 or request.max_accounts > 64:
        _add(blockers, "MPR02_V6_BAD_MAX_ACCOUNTS", "maxAccounts must be 1..64")
    if request.blockhash_slots_to_expiry < 1 or request.blockhash_slots_to_expiry > 300:
        _add(blockers, "MPR02_V6_BAD_BLOCKHASH_SLOTS_TO_EXPIRY", "blockhashSlotsToExpiry must be 1..300")
    if request.swap_mode is not None:
        _add(blockers, "MPR02_V6_SWAP_MODE_NOT_SUPPORTED", "/swap/v2/build is ExactIn-only")


def _jupiter_response(response: JupiterV2BuildResponse, blockers: list[MPR02V6Violation]) -> None:
    _require_hash(blockers, "MPR02_V6_BAD_BLOCKHASH_METADATA_HASH", blockhash_metadata_sha256=response.blockhash_metadata_sha256)
    if response.last_valid_block_height <= 0:
        _add(blockers, "MPR02_V6_BAD_LAST_VALID_BLOCK_HEIGHT", "lastValidBlockHeight must be positive")
    if response.current_rooted_block_height < 0:
        _add(blockers, "MPR02_V6_BAD_CURRENT_ROOTED_HEIGHT", "current rooted block height cannot be negative")
    if response.remaining_height_margin <= 0:
        _add(blockers, "MPR02_V6_BAD_HEIGHT_MARGIN", "remaining height margin must be positive")
    remaining = response.last_valid_block_height - response.current_rooted_block_height
    if remaining < response.remaining_height_margin:
        _add(blockers, "MPR02_V6_BLOCKHASH_TOO_CLOSE_TO_EXPIRY", "blockhash lifetime margin is insufficient")
    if not response.route_plan:
        _add(blockers, "MPR02_V6_EMPTY_ROUTE_PLAN", "routePlan must be non-empty")
        return
    bps_sum = 0
    previous_output: str | None = None
    for index, segment in enumerate(response.route_plan):
        if not isinstance(segment.bps, int) or segment.bps < 1 or segment.bps > 10_000:
            _add(blockers, "MPR02_V6_BAD_ROUTE_BPS", "each route bps must be 1..10000")
        else:
            bps_sum += segment.bps
        for name, value in (("input_mint", segment.input_mint), ("output_mint", segment.output_mint), ("amm_key", segment.amm_key), ("program_id", segment.program_id)):
            if not _pubkey(value):
                _add(blockers, "MPR02_V6_BAD_ROUTE_PUBKEY", f"route[{index}].{name} is invalid")
        if not _safe_label(segment.label):
            _add(blockers, "MPR02_V6_BAD_ROUTE_LABEL", f"route[{index}] label is invalid")
        if not _u64_positive(segment.in_amount) or not _u64_positive(segment.out_amount):
            _add(blockers, "MPR02_V6_BAD_ROUTE_AMOUNT", "route in/out amounts must be positive u64")
        _swap_info(index, segment, blockers)
        if index == 0 and segment.input_mint != response.top_level_input_mint:
            _add(blockers, "MPR02_V6_ROUTE_INPUT_MISMATCH", "first route input mint must match top-level input")
        if index == len(response.route_plan) - 1 and segment.output_mint != response.top_level_output_mint:
            _add(blockers, "MPR02_V6_ROUTE_OUTPUT_MISMATCH", "last route output mint must match top-level output")
        if previous_output is not None and segment.input_mint != previous_output:
            _add(blockers, "MPR02_V6_ROUTE_MINT_DISCONTINUITY", "route mints must be continuous")
        previous_output = segment.output_mint
    if bps_sum != 10_000:
        _add(blockers, "MPR02_V6_ROUTE_BPS_SUM_MISMATCH", "route bps must sum exactly to 10000")


def _swap_info(index: int, segment: RoutePlanSegment, blockers: list[MPR02V6Violation]) -> None:
    required = {
        "ammKey": segment.amm_key,
        "label": segment.label,
        "inputMint": segment.input_mint,
        "outputMint": segment.output_mint,
        "inAmount": str(segment.in_amount),
        "outAmount": str(segment.out_amount),
    }
    for key, expected in required.items():
        if segment.swap_info.get(key) != expected:
            _add(blockers, "MPR02_V6_INCOMPLETE_SWAP_INFO", f"route[{index}].swapInfo[{key!r}] must be {expected!r}")


def _marginfi_accounts(accounts: Sequence[MarginFiTokenAccountEvidence], blockers: list[MPR02V6Violation]) -> None:
    if not accounts:
        _add(blockers, "MPR02_V6_MARGINFI_ACCOUNT_EVIDENCE_REQUIRED", "borrow/repay account evidence required")
    for index, account in enumerate(accounts):
        for name, value in (("account_pubkey", account.account_pubkey), ("token_program_id", account.token_program_id), ("owner_program_id", account.owner_program_id), ("mint", account.mint), ("expected_mint", account.expected_mint), ("authority", account.authority), ("expected_authority", account.expected_authority)):
            if not _pubkey(value):
                _add(blockers, "MPR02_V6_BAD_MARGINFI_PUBKEY", f"account[{index}].{name} invalid")
        if account.token_program_id not in {OFFICIAL_TOKEN_PROGRAM_ID, OFFICIAL_TOKEN_2022_PROGRAM_ID}:
            _add(blockers, "MPR02_V6_BAD_MARGINFI_TOKEN_PROGRAM", "token program must be canonical")
        if account.owner_program_id != account.token_program_id:
            _add(blockers, "MPR02_V6_TOKEN_ACCOUNT_OWNER_MISMATCH", "account owner must match token program")
        if account.mint != account.expected_mint:
            _add(blockers, "MPR02_V6_TOKEN_ACCOUNT_MINT_MISMATCH", "account mint must match admitted bank mint")
        if account.authority != account.expected_authority:
            _add(blockers, "MPR02_V6_TOKEN_ACCOUNT_AUTHORITY_MISMATCH", "account authority must match payer/margin authority")
        _require_hash(blockers, "MPR02_V6_BAD_RAW_ACCOUNT_HASH", raw_account_sha256=account.raw_account_sha256)
        if account.rooted_slot <= 0:
            _add(blockers, "MPR02_V6_BAD_ROOTED_SLOT", "account evidence must be rooted")
        if account.frozen:
            _add(blockers, "MPR02_V6_TOKEN_ACCOUNT_FROZEN", "frozen token account cannot be used")
        if account.delegate_present:
            _add(blockers, "MPR02_V6_TOKEN_ACCOUNT_DELEGATE_PRESENT", "delegate state must fail closed")
        if account.native_lamports_present:
            _add(blockers, "MPR02_V6_NATIVE_TOKEN_ACCOUNT_UNSUPPORTED", "native token accounts need explicit proof")
        if not account.included_in_final_instruction_accounts:
            _add(blockers, "MPR02_V6_ACCOUNT_NOT_IN_FINAL_MESSAGE", "borrow/repay account must be present in final compiled instruction set")


def _token2022_rent(rent: Token2022RentEvidence, blockers: list[MPR02V6Violation]) -> None:
    if rent.token_program_id not in {OFFICIAL_TOKEN_PROGRAM_ID, OFFICIAL_TOKEN_2022_PROGRAM_ID}:
        _add(blockers, "MPR02_V6_BAD_RENT_TOKEN_PROGRAM", "rent evidence token program is not canonical")
    if rent.base_account_size != 165:
        _add(blockers, "MPR02_V6_BAD_BASE_ACCOUNT_SIZE", "base SPL token account size must be 165")
    if any(size <= 0 for size in rent.extension_sizes):
        _add(blockers, "MPR02_V6_BAD_EXTENSION_SIZE", "extension sizes must be positive")
    exact_size = rent.base_account_size + sum(rent.extension_sizes)
    if rent.token_program_id == OFFICIAL_TOKEN_2022_PROGRAM_ID and exact_size <= 165:
        _add(blockers, "MPR02_V6_TOKEN2022_EXTENSION_SIZE_REQUIRED", "Token-2022 rent must be extension-aware")
    if rent.rent_exempt_lamports <= 0:
        _add(blockers, "MPR02_V6_BAD_RENT_LAMPORTS", "rent-exempt lamports must be positive")
    if rent.rent_context_slot <= 0:
        _add(blockers, "MPR02_V6_BAD_RENT_CONTEXT", "rent context slot must be rooted/coherent")
    _require_hash(blockers, "MPR02_V6_BAD_RENT_HASH", rent_response_sha256=rent.rent_response_sha256, final_create_account_instruction_sha256=rent.final_create_account_instruction_sha256)


def _ca_bundle(ca: CABundleEvidence, blockers: list[MPR02V6Violation]) -> None:
    _require_hash(blockers, "MPR02_V6_BAD_CA_HASH", expected_sha256=ca.expected_sha256, reviewed_bytes_sha256=ca.reviewed_bytes_sha256, ssl_loaded_bytes_sha256=ca.ssl_loaded_bytes_sha256, private_copy_inode_sha256=ca.private_copy_inode_sha256)
    if len({ca.expected_sha256, ca.reviewed_bytes_sha256, ca.ssl_loaded_bytes_sha256, ca.private_copy_inode_sha256}) != 1:
        _add(blockers, "MPR02_V6_CA_HASH_LOAD_MISMATCH", "reviewed, copied and SSL-loaded CA bytes must match")
    if ca.check_then_reopen_path:
        _add(blockers, "MPR02_V6_CA_CHECK_THEN_REOPEN", "CA bundle must not be hashed then reopened from mutable path")
    if not _sha256_uri(ca.deployment_image_digest):
        _add(blockers, "MPR02_V6_BAD_IMAGE_DIGEST", "deployment image digest must be sha256:<hex>")


def _capability_requests(evidence: MPR02V6Evidence, blockers: list[MPR02V6Violation]) -> None:
    if evidence.operational_paper_ready_requested:
        _add(blockers, "MPR02_V6_PAPER_READY_PROMOTION_FORBIDDEN", "MPR-02 V6 cannot promote operational paper")
    if evidence.live_execution_requested:
        _add(blockers, "MPR02_V6_LIVE_FORBIDDEN", "MPR-02 V6 cannot enable live execution")
    if evidence.sender_requested:
        _add(blockers, "MPR02_V6_SENDER_FORBIDDEN", "MPR-02 V6 cannot enable sender paths")


def _stable_hash(value: Any) -> str:
    payload = json.dumps(_jsonable(value), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _jsonable(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return {key: _jsonable(val) for key, val in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): _jsonable(val) for key, val in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, StrEnum):
        return str(value)
    return value


def _dedupe(items: Sequence[MPR02V6Violation]) -> list[MPR02V6Violation]:
    seen: set[str] = set()
    result: list[MPR02V6Violation] = []
    for item in items:
        key = f"{item.code}:{item.message}"
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def _add(out: list[MPR02V6Violation], code: str, message: str) -> None:
    out.append(MPR02V6Violation(code=code, message=message))


def _pubkey(value: str) -> bool:
    return isinstance(value, str) and bool(_BASE58_RE.fullmatch(value))


def _sha(value: str) -> bool:
    return isinstance(value, str) and bool(_SHA256_RE.fullmatch(value))


def _sha256_uri(value: str) -> bool:
    return isinstance(value, str) and bool(_SHA256_URI_RE.fullmatch(value))


def _safe_label(value: str) -> bool:
    return isinstance(value, str) and bool(_SAFE_LABEL_RE.fullmatch(value))


def _u64_positive(value: int) -> bool:
    return isinstance(value, int) and 0 < value <= U64_MAX


def _require_hash(out: list[MPR02V6Violation], code: str, **values: str) -> None:
    bad = [name for name, value in values.items() if not _sha(value)]
    if bad:
        _add(out, code, f"invalid sha256 fields: {bad}")
