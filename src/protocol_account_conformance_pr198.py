"""PR-198 protocol/account conformance authority.

This module is deliberately sender-free.  It validates already-materialized
protocol, mint, token-account, ATA, wSOL and deployment evidence before a
MarginFi/Kamino path can be considered usable for shadow planning.  Live
execution remains impossible from this module.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Any

from src.config.chain_registry import (
    ASSOCIATED_TOKEN_PROGRAM_ADDRESS,
    BPF_UPGRADEABLE_LOADER_ADDRESS,
    NATIVE_SOL_MINT_ADDRESS,
    TOKEN_2022_PROGRAM_ADDRESS,
    TOKEN_PROGRAM_ADDRESS,
    ChainRegistryError,
    validate_pubkey,
)

SCHEMA_VERSION = "pr198.protocol-account-conformance.v1"
RESULT_SCHEMA_VERSION = "pr198.protocol-account-conformance-result.v1"
SUPPORTED_TOKEN_PROGRAMS = frozenset(
    {TOKEN_PROGRAM_ADDRESS, TOKEN_2022_PROGRAM_ADDRESS}
)
SUPPORTED_TOKEN_2022_EXTENSIONS: frozenset[str] = frozenset()
SUPPORTED_DEFAULT_ACCOUNT_STATES = frozenset({"initialized"})
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ProtocolAccountConformanceError(ValueError):
    """Raised when PR-198 evidence is malformed."""


class ProtocolName(StrEnum):
    MARGINFI = "marginfi"
    KAMINO = "kamino"


class KaminoProductionDecision(StrEnum):
    UNSUPPORTED_REMOVED = "unsupported-removed"
    SUPPORTED_WITH_EVIDENCE = "supported-with-evidence"


class ProtocolConformanceState(StrEnum):
    SHADOW_CONFORMANT = "shadow-conformant"
    BLOCKED = "blocked"


def _require_non_empty(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProtocolAccountConformanceError(f"{field} must be a non-empty string")
    return value.strip()


def _require_pubkey(value: object, *, field: str) -> str:
    try:
        return validate_pubkey(str(value), field=field)
    except ChainRegistryError as exc:
        raise ProtocolAccountConformanceError(str(exc)) from exc


def _optional_pubkey(value: object, *, field: str) -> str | None:
    if value in (None, ""):
        return None
    return _require_pubkey(value, field=field)


def _require_bool(value: object, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise ProtocolAccountConformanceError(f"{field} must be boolean")
    return value


def _require_int(value: object, *, field: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProtocolAccountConformanceError(f"{field} must be an integer")
    if value < minimum:
        raise ProtocolAccountConformanceError(f"{field} must be >= {minimum}")
    return value


def _require_sha256(value: object, *, field: str) -> str:
    digest = str(value).lower()
    if not _SHA256_RE.fullmatch(digest) or digest == "0" * 64:
        raise ProtocolAccountConformanceError(
            f"{field} must be a non-placeholder sha256 digest"
        )
    return digest


def _tuple_of_strings(value: Iterable[object], *, field: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)):
        raise ProtocolAccountConformanceError(f"{field} must be an iterable of strings")
    normalized = tuple(_require_non_empty(item, field=field) for item in value)
    if len(normalized) != len(set(normalized)):
        raise ProtocolAccountConformanceError(f"{field} must not contain duplicates")
    return normalized


def stable_json(payload: Any) -> str:
    return json.dumps(
        _jsonable(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def sha256_payload(payload: Any) -> str:
    return hashlib.sha256(stable_json(payload).encode("utf-8")).hexdigest()


def ata_derivation_proof_sha256(
    *,
    wallet_owner: str,
    mint: str,
    token_program_id: str,
    associated_token_program_id: str = ASSOCIATED_TOKEN_PROGRAM_ADDRESS,
) -> str:
    """Return the PR-198 stable proof hash for a materialized ATA derivation.

    This does not claim to be the Solana PDA address itself.  The actual address
    must be supplied as observed account evidence.  The hash binds the canonical
    ATA seeds so replayed evidence cannot silently swap wallet/mint/token-program
    semantics without changing the proof identity.
    """

    payload = {
        "schema_version": "pr198.ata-derivation-proof.v1",
        "wallet_owner": _require_pubkey(wallet_owner, field="wallet_owner"),
        "mint": _require_pubkey(mint, field="mint"),
        "token_program_id": _require_pubkey(
            token_program_id,
            field="token_program_id",
        ),
        "associated_token_program_id": _require_pubkey(
            associated_token_program_id,
            field="associated_token_program_id",
        ),
    }
    return sha256_payload(payload)


@dataclass(frozen=True, slots=True)
class TokenMintEvidence:
    mint: str
    token_program_id: str
    decimals: int
    supply: int
    initialized: bool
    default_account_state: str = "initialized"
    freeze_authority: str | None = None
    token_2022_extensions: tuple[str, ...] = ()
    transfer_fee_configured: bool = False
    transfer_hook_program_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "mint", _require_pubkey(self.mint, field="mint"))
        object.__setattr__(
            self,
            "token_program_id",
            _require_pubkey(self.token_program_id, field="token_program_id"),
        )
        _require_int(self.decimals, field="decimals")
        if self.decimals > 19:
            raise ProtocolAccountConformanceError("decimals must be <= 19")
        _require_int(self.supply, field="supply")
        _require_bool(self.initialized, field="initialized")
        object.__setattr__(
            self,
            "default_account_state",
            _require_non_empty(
                self.default_account_state,
                field="default_account_state",
            ),
        )
        object.__setattr__(
            self,
            "freeze_authority",
            _optional_pubkey(self.freeze_authority, field="freeze_authority"),
        )
        object.__setattr__(
            self,
            "token_2022_extensions",
            _tuple_of_strings(
                self.token_2022_extensions, field="token_2022_extensions"
            ),
        )
        _require_bool(self.transfer_fee_configured, field="transfer_fee_configured")
        object.__setattr__(
            self,
            "transfer_hook_program_id",
            _optional_pubkey(
                self.transfer_hook_program_id,
                field="transfer_hook_program_id",
            ),
        )


@dataclass(frozen=True, slots=True)
class TokenAccountEvidence:
    account_address: str
    owner_wallet: str
    mint: str
    token_program_id: str
    amount: int
    lamports: int
    rent_exempt_minimum_lamports: int
    initialized: bool = True
    frozen: bool = False
    delegate: str | None = None
    close_authority: str | None = None
    native_lamports: int | None = None
    created_by_attempt: bool = False
    pre_existing: bool = True

    def __post_init__(self) -> None:
        for field_name in (
            "account_address",
            "owner_wallet",
            "mint",
            "token_program_id",
        ):
            object.__setattr__(
                self,
                field_name,
                _require_pubkey(getattr(self, field_name), field=field_name),
            )
        for field_name in ("amount", "lamports", "rent_exempt_minimum_lamports"):
            _require_int(getattr(self, field_name), field=field_name)
        if self.native_lamports is not None:
            _require_int(self.native_lamports, field="native_lamports")
        for field_name in (
            "initialized",
            "frozen",
            "created_by_attempt",
            "pre_existing",
        ):
            _require_bool(getattr(self, field_name), field=field_name)
        object.__setattr__(
            self, "delegate", _optional_pubkey(self.delegate, field="delegate")
        )
        object.__setattr__(
            self,
            "close_authority",
            _optional_pubkey(self.close_authority, field="close_authority"),
        )


@dataclass(frozen=True, slots=True)
class AssociatedTokenAccountEvidence:
    ata_address: str
    wallet_owner: str
    mint: str
    token_program_id: str
    derivation_proof_sha256: str
    associated_token_program_id: str = ASSOCIATED_TOKEN_PROGRAM_ADDRESS

    def __post_init__(self) -> None:
        for field_name in (
            "ata_address",
            "wallet_owner",
            "mint",
            "token_program_id",
            "associated_token_program_id",
        ):
            object.__setattr__(
                self,
                field_name,
                _require_pubkey(getattr(self, field_name), field=field_name),
            )
        object.__setattr__(
            self,
            "derivation_proof_sha256",
            _require_sha256(
                self.derivation_proof_sha256, field="derivation_proof_sha256"
            ),
        )


@dataclass(frozen=True, slots=True)
class WsolLifecycleEvidence:
    account_address: str
    owner_wallet: str
    amount_lamports: int
    rent_reserve_lamports: int
    created_by_attempt: bool
    pre_existing_balance_lamports: int
    may_close_after_attempt: bool
    close_destination: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("account_address", "owner_wallet"):
            object.__setattr__(
                self,
                field_name,
                _require_pubkey(getattr(self, field_name), field=field_name),
            )
        for field_name in (
            "amount_lamports",
            "rent_reserve_lamports",
            "pre_existing_balance_lamports",
        ):
            _require_int(getattr(self, field_name), field=field_name)
        for field_name in ("created_by_attempt", "may_close_after_attempt"):
            _require_bool(getattr(self, field_name), field=field_name)
        object.__setattr__(
            self,
            "close_destination",
            _optional_pubkey(self.close_destination, field="close_destination"),
        )


@dataclass(frozen=True, slots=True)
class ProgramDeploymentEvidence:
    program_id: str
    loader_program_id: str
    programdata_address: str
    executable: bool
    binary_sha256: str
    idl_sha256: str
    attestation_sha256: str
    attested_slot: int
    observed_slot: int
    expiry_slot: int
    upgrade_authority: str | None = None
    upgrade_authority_revoked: bool = False

    def __post_init__(self) -> None:
        for field_name in ("program_id", "loader_program_id", "programdata_address"):
            object.__setattr__(
                self,
                field_name,
                _require_pubkey(getattr(self, field_name), field=field_name),
            )
        _require_bool(self.executable, field="executable")
        for field_name in ("binary_sha256", "idl_sha256", "attestation_sha256"):
            object.__setattr__(
                self,
                field_name,
                _require_sha256(getattr(self, field_name), field=field_name),
            )
        for field_name in ("attested_slot", "observed_slot", "expiry_slot"):
            _require_int(getattr(self, field_name), field=field_name, minimum=1)
        object.__setattr__(
            self,
            "upgrade_authority",
            _optional_pubkey(self.upgrade_authority, field="upgrade_authority"),
        )
        _require_bool(self.upgrade_authority_revoked, field="upgrade_authority_revoked")


@dataclass(frozen=True, slots=True)
class ProtocolDecisionEvidence:
    protocol: ProtocolName
    credentialed_evidence_complete: bool
    kamino_decision: KaminoProductionDecision | None = None
    supported_combinations: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "protocol", ProtocolName(self.protocol))
        _require_bool(
            self.credentialed_evidence_complete,
            field="credentialed_evidence_complete",
        )
        if self.kamino_decision is not None:
            object.__setattr__(
                self,
                "kamino_decision",
                KaminoProductionDecision(self.kamino_decision),
            )
        _require_int(self.supported_combinations, field="supported_combinations")


@dataclass(frozen=True, slots=True)
class ProtocolAccountConformanceBundle:
    protocol_decision: ProtocolDecisionEvidence
    deployment: ProgramDeploymentEvidence
    mints: tuple[TokenMintEvidence, ...]
    token_accounts: tuple[TokenAccountEvidence, ...]
    ata_accounts: tuple[AssociatedTokenAccountEvidence, ...]
    wsol_lifecycles: tuple[WsolLifecycleEvidence, ...] = ()
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ProtocolAccountConformanceError("unexpected PR-198 bundle schema")
        for field_name in (
            "mints",
            "token_accounts",
            "ata_accounts",
            "wsol_lifecycles",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, tuple):
                object.__setattr__(self, field_name, tuple(value))


@dataclass(frozen=True, slots=True)
class ProtocolAccountConformanceReport:
    schema_version: str
    state: ProtocolConformanceState
    shadow_protocol_usable: bool
    live_execution_allowed: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    evidence_hash: str
    checks_evaluated: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "state": self.state.value,
            "shadow_protocol_usable": self.shadow_protocol_usable,
            "live_execution_allowed": self.live_execution_allowed,
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "evidence_hash": self.evidence_hash,
            "checks_evaluated": self.checks_evaluated,
        }


def evaluate_protocol_account_conformance(
    bundle: ProtocolAccountConformanceBundle,
    *,
    current_slot: int,
) -> ProtocolAccountConformanceReport:
    """Evaluate PR-198 evidence and fail closed on any protocol/account drift."""

    _require_int(current_slot, field="current_slot", minimum=1)
    blockers: list[str] = []
    warnings: list[str] = []
    checks = 0

    def check(condition: bool, code: str) -> None:
        nonlocal checks
        checks += 1
        if not condition:
            blockers.append(code)

    _evaluate_protocol_decision(bundle.protocol_decision, check)
    _evaluate_deployment(bundle.deployment, current_slot=current_slot, check=check)

    mint_by_address: dict[str, TokenMintEvidence] = {}
    for mint in bundle.mints:
        check(mint.mint not in mint_by_address, f"DUPLICATE_MINT:{mint.mint}")
        mint_by_address[mint.mint] = mint
        _evaluate_mint(mint, check=check)

    account_by_address: dict[str, TokenAccountEvidence] = {}
    for account in bundle.token_accounts:
        check(
            account.account_address not in account_by_address,
            f"DUPLICATE_TOKEN_ACCOUNT:{account.account_address}",
        )
        account_by_address[account.account_address] = account
        _evaluate_token_account(account, mint_by_address=mint_by_address, check=check)

    for ata in bundle.ata_accounts:
        _evaluate_ata(ata, account_by_address=account_by_address, check=check)

    for lifecycle in bundle.wsol_lifecycles:
        _evaluate_wsol_lifecycle(
            lifecycle,
            account_by_address=account_by_address,
            check=check,
        )

    unique_blockers = tuple(dict.fromkeys(blockers))
    state = (
        ProtocolConformanceState.SHADOW_CONFORMANT
        if not unique_blockers
        else ProtocolConformanceState.BLOCKED
    )
    if state is ProtocolConformanceState.SHADOW_CONFORMANT:
        warnings.append("PR198_SHADOW_ONLY_LIVE_REMAINS_DENIED")

    return ProtocolAccountConformanceReport(
        schema_version=RESULT_SCHEMA_VERSION,
        state=state,
        shadow_protocol_usable=not unique_blockers,
        live_execution_allowed=False,
        blockers=unique_blockers,
        warnings=tuple(dict.fromkeys(warnings)),
        evidence_hash=sha256_payload(bundle),
        checks_evaluated=checks,
    )


def _evaluate_protocol_decision(
    decision: ProtocolDecisionEvidence,
    check: Any,
) -> None:
    if decision.protocol is ProtocolName.MARGINFI:
        check(
            decision.credentialed_evidence_complete,
            "MARGINFI_CREDENTIALLED_EVIDENCE_MISSING",
        )
        return

    if decision.protocol is ProtocolName.KAMINO:
        check(
            decision.kamino_decision is not None, "KAMINO_PRODUCTION_DECISION_MISSING"
        )
        if decision.kamino_decision is KaminoProductionDecision.UNSUPPORTED_REMOVED:
            check(
                decision.supported_combinations == 0,
                "KAMINO_REMOVED_BUT_COMBINATIONS_PRESENT",
            )
            return
        check(
            decision.credentialed_evidence_complete,
            "KAMINO_CREDENTIALLED_EVIDENCE_MISSING",
        )
        check(
            decision.supported_combinations > 0,
            "KAMINO_SUPPORTED_COMBINATIONS_EMPTY",
        )


def _evaluate_deployment(
    deployment: ProgramDeploymentEvidence,
    *,
    current_slot: int,
    check: Any,
) -> None:
    check(deployment.executable, "PROGRAM_NOT_EXECUTABLE")
    check(
        deployment.loader_program_id == BPF_UPGRADEABLE_LOADER_ADDRESS,
        "PROGRAM_LOADER_NOT_BPF_UPGRADEABLE",
    )
    check(
        deployment.observed_slot >= deployment.attested_slot,
        "PROGRAM_OBSERVED_BEFORE_ATTESTED_SLOT",
    )
    check(current_slot <= deployment.expiry_slot, "PROGRAM_ATTESTATION_EXPIRED")
    check(
        deployment.upgrade_authority is None or deployment.upgrade_authority_revoked,
        "PROGRAM_UPGRADE_AUTHORITY_NOT_REVOKED",
    )


def _evaluate_mint(mint: TokenMintEvidence, *, check: Any) -> None:
    check(mint.initialized, f"MINT_NOT_INITIALIZED:{mint.mint}")
    check(
        mint.token_program_id in SUPPORTED_TOKEN_PROGRAMS,
        f"UNSUPPORTED_TOKEN_PROGRAM:{mint.mint}",
    )
    check(
        mint.default_account_state in SUPPORTED_DEFAULT_ACCOUNT_STATES,
        f"UNSUPPORTED_DEFAULT_ACCOUNT_STATE:{mint.mint}:{mint.default_account_state}",
    )
    if mint.token_program_id == TOKEN_2022_PROGRAM_ADDRESS:
        for extension in mint.token_2022_extensions:
            check(
                extension in SUPPORTED_TOKEN_2022_EXTENSIONS,
                f"TOKEN_2022_UNSUPPORTED_EXTENSION:{mint.mint}:{extension}",
            )
        check(
            not mint.transfer_fee_configured,
            f"TOKEN_2022_TRANSFER_FEE_UNSUPPORTED:{mint.mint}",
        )
        check(
            mint.transfer_hook_program_id is None,
            f"TOKEN_2022_TRANSFER_HOOK_UNSUPPORTED:{mint.mint}",
        )


def _evaluate_token_account(
    account: TokenAccountEvidence,
    *,
    mint_by_address: Mapping[str, TokenMintEvidence],
    check: Any,
) -> None:
    mint = mint_by_address.get(account.mint)
    check(
        mint is not None, f"TOKEN_ACCOUNT_MINT_NOT_REGISTERED:{account.account_address}"
    )
    if mint is not None:
        check(
            account.token_program_id == mint.token_program_id,
            f"TOKEN_ACCOUNT_PROGRAM_MISMATCH:{account.account_address}",
        )
    check(
        account.initialized, f"TOKEN_ACCOUNT_NOT_INITIALIZED:{account.account_address}"
    )
    check(not account.frozen, f"TOKEN_ACCOUNT_FROZEN:{account.account_address}")
    check(
        account.lamports >= account.rent_exempt_minimum_lamports,
        f"TOKEN_ACCOUNT_NOT_RENT_EXEMPT:{account.account_address}",
    )
    check(
        account.delegate is None,
        f"TOKEN_ACCOUNT_HAS_DELEGATE:{account.account_address}",
    )


def _evaluate_ata(
    ata: AssociatedTokenAccountEvidence,
    *,
    account_by_address: Mapping[str, TokenAccountEvidence],
    check: Any,
) -> None:
    account = account_by_address.get(ata.ata_address)
    check(account is not None, f"ATA_ACCOUNT_MISSING:{ata.ata_address}")
    if account is not None:
        check(
            account.owner_wallet == ata.wallet_owner,
            f"ATA_OWNER_MISMATCH:{ata.ata_address}",
        )
        check(account.mint == ata.mint, f"ATA_MINT_MISMATCH:{ata.ata_address}")
        check(
            account.token_program_id == ata.token_program_id,
            f"ATA_TOKEN_PROGRAM_MISMATCH:{ata.ata_address}",
        )
    check(
        ata.associated_token_program_id == ASSOCIATED_TOKEN_PROGRAM_ADDRESS,
        "ASSOCIATED_TOKEN_PROGRAM_MISMATCH",
    )
    expected = ata_derivation_proof_sha256(
        wallet_owner=ata.wallet_owner,
        mint=ata.mint,
        token_program_id=ata.token_program_id,
        associated_token_program_id=ata.associated_token_program_id,
    )
    check(
        ata.derivation_proof_sha256 == expected,
        f"ATA_DERIVATION_PROOF_MISMATCH:{ata.ata_address}",
    )


def _evaluate_wsol_lifecycle(
    lifecycle: WsolLifecycleEvidence,
    *,
    account_by_address: Mapping[str, TokenAccountEvidence],
    check: Any,
) -> None:
    account = account_by_address.get(lifecycle.account_address)
    check(account is not None, f"WSOL_ACCOUNT_MISSING:{lifecycle.account_address}")
    if account is not None:
        check(account.mint == NATIVE_SOL_MINT_ADDRESS, "WSOL_ACCOUNT_MINT_MISMATCH")
        check(
            account.owner_wallet == lifecycle.owner_wallet,
            "WSOL_ACCOUNT_OWNER_MISMATCH",
        )
        check(
            account.amount == lifecycle.amount_lamports,
            "WSOL_AMOUNT_MISMATCH",
        )
        check(
            account.native_lamports == lifecycle.amount_lamports,
            "WSOL_NATIVE_LAMPORTS_MISMATCH",
        )
    check(
        lifecycle.created_by_attempt or not lifecycle.may_close_after_attempt,
        "WSOL_CLOSE_REQUIRES_ATTEMPT_CREATED_ACCOUNT",
    )
    check(
        lifecycle.pre_existing_balance_lamports == 0
        or not lifecycle.may_close_after_attempt,
        "WSOL_PRE_EXISTING_BALANCE_CLOSE_FORBIDDEN",
    )
    if lifecycle.may_close_after_attempt:
        check(
            lifecycle.close_destination == lifecycle.owner_wallet,
            "WSOL_CLOSE_DESTINATION_MISMATCH",
        )
    check(
        lifecycle.rent_reserve_lamports > 0,
        "WSOL_RENT_RESERVE_MISSING",
    )


def _jsonable(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return {
            field_name: _jsonable(getattr(value, field_name))
            for field_name in value.__dataclass_fields__
        }
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value
