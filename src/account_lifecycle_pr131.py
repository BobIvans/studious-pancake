"""PR-131 deterministic ATA, wSOL and rent lifecycle proofs.

This module is intentionally sender-free and network-free. It models the
account setup and cleanup evidence that must exist before a later planner may
compile a final message.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping

from solders.pubkey import Pubkey

SYSTEM_PROGRAM_ID = "11111111111111111111111111111111"
SPL_TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM_ID = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
ASSOCIATED_TOKEN_PROGRAM_ID = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
NATIVE_SOL_MINT = "So11111111111111111111111111111111111111112"
TOKEN_ACCOUNT_BASE_DATA_SIZE = 165


class AccountLifecycleReason(StrEnum):
    INVALID_PUBKEY = "pr131_invalid_pubkey"
    IMPLICIT_JUPITER_DEFAULT = "pr131_implicit_jupiter_default"
    INVALID_JUPITER_LIFECYCLE_FIELD = "pr131_invalid_jupiter_lifecycle_field"
    ATA_ADDRESS_MISMATCH = "pr131_ata_address_mismatch"
    ATA_OWNER_MISMATCH = "pr131_ata_owner_mismatch"
    ATA_MINT_MISMATCH = "pr131_ata_mint_mismatch"
    ATA_TOKEN_PROGRAM_MISMATCH = "pr131_ata_token_program_mismatch"
    ATA_CREATE_NOT_IDEMPOTENT = "pr131_ata_create_not_idempotent"
    INSUFFICIENT_RENT_RESERVATION = "pr131_insufficient_rent_reservation"
    PRE_BORROW_PAYER_DEBIT = "pr131_pre_borrow_payer_debit"
    FLASH_PRINCIPAL_PRE_BORROW = "pr131_flash_principal_pre_borrow"
    WSOL_SYNC_MISSING = "pr131_wsol_sync_missing"
    WSOL_CLOSE_DESTINATION = "pr131_wsol_close_destination"
    CLEANUP_PREEXISTING_ACCOUNT = "pr131_cleanup_preexisting_account"
    CLEANUP_AUTHORITY_CHANGE = "pr131_cleanup_authority_change"
    DUPLICATE_ATA_PLAN = "pr131_duplicate_ata_plan"
    CONFLICTING_CLEANUP = "pr131_conflicting_cleanup"


class AccountLifecycleError(ValueError):
    def __init__(
        self,
        reason: AccountLifecycleReason,
        message: str,
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(f"{reason.value}: {message}")
        self.reason = reason
        self.details = dict(details or {})


class LifecycleStage(StrEnum):
    PRE_BORROW_OWN_CAPITAL = "pre_borrow_own_capital"
    POST_BORROW_FLASH_PRINCIPAL = "post_borrow_flash_principal"
    ROUTE_SETUP = "route_setup"
    SWAP = "swap"
    PRE_REPAY_CLEANUP = "pre_repay_cleanup"
    POST_REPAY_CLEANUP = "post_repay_cleanup"


class WsolFundingSource(StrEnum):
    PAYER_RESERVED_SOL = "payer_reserved_sol"
    FLASH_PRINCIPAL = "flash_principal"


@dataclass(frozen=True, slots=True)
class AccountLifecycleFinding:
    semantic_class: str
    account: str
    lamports_reserved: int = 0
    stage: LifecycleStage | None = None


@dataclass(frozen=True, slots=True)
class JupiterLifecycleParams:
    input_mint: str
    output_mint: str
    amount: int
    taker: str
    payer: str
    slippage_bps: int
    wrap_and_unwrap_sol: bool
    max_accounts: int
    blockhash_slots_to_expiry: int
    for_jito_bundle: bool
    swap_mode: str
    destination_token_account: str | None = None
    native_destination_account: str | None = None

    def __post_init__(self) -> None:
        _parse_pubkey(self.input_mint)
        _parse_pubkey(self.output_mint)
        _parse_pubkey(self.taker)
        _parse_pubkey(self.payer)
        if self.destination_token_account is not None:
            _parse_pubkey(self.destination_token_account)
        if self.native_destination_account is not None:
            _parse_pubkey(self.native_destination_account)
        if self.destination_token_account and self.native_destination_account:
            raise AccountLifecycleError(
                AccountLifecycleReason.INVALID_JUPITER_LIFECYCLE_FIELD,
                "destinationTokenAccount and nativeDestinationAccount conflict",
            )
        if self.amount <= 0:
            raise AccountLifecycleError(
                AccountLifecycleReason.INVALID_JUPITER_LIFECYCLE_FIELD,
                "amount must be positive",
            )
        if not (1 <= self.max_accounts <= 64):
            raise AccountLifecycleError(
                AccountLifecycleReason.INVALID_JUPITER_LIFECYCLE_FIELD,
                "maxAccounts must be between 1 and 64",
            )
        if not (1 <= self.blockhash_slots_to_expiry <= 300):
            raise AccountLifecycleError(
                AccountLifecycleReason.INVALID_JUPITER_LIFECYCLE_FIELD,
                "blockhashSlotsToExpiry must be between 1 and 300",
            )
        if self.swap_mode not in {"ExactIn", "ExactOut"}:
            raise AccountLifecycleError(
                AccountLifecycleReason.INVALID_JUPITER_LIFECYCLE_FIELD,
                "swapMode must be ExactIn or ExactOut",
            )

    def to_build_params(self) -> dict[str, str]:
        params = {
            "inputMint": self.input_mint,
            "outputMint": self.output_mint,
            "amount": str(self.amount),
            "taker": self.taker,
            "payer": self.payer,
            "slippageBps": str(self.slippage_bps),
            "wrapAndUnwrapSol": _lower_bool(self.wrap_and_unwrap_sol),
            "maxAccounts": str(self.max_accounts),
            "blockhashSlotsToExpiry": str(self.blockhash_slots_to_expiry),
            "forJitoBundle": _lower_bool(self.for_jito_bundle),
            "swapMode": self.swap_mode,
        }
        if self.destination_token_account:
            params["destinationTokenAccount"] = self.destination_token_account
        if self.native_destination_account:
            params["nativeDestinationAccount"] = self.native_destination_account
        return params


@dataclass(frozen=True, slots=True)
class RentEvidence:
    data_size: int
    rent_exempt_lamports: int
    source: str
    endpoint_id: str
    context_slot: int | None = None

    def __post_init__(self) -> None:
        if self.data_size <= 0 or self.rent_exempt_lamports <= 0:
            raise AccountLifecycleError(
                AccountLifecycleReason.INSUFFICIENT_RENT_RESERVATION,
                "rent evidence must include positive size and lamports",
            )
        if not self.source or not self.endpoint_id:
            raise AccountLifecycleError(
                AccountLifecycleReason.INSUFFICIENT_RENT_RESERVATION,
                "rent evidence must include source and endpoint",
            )


@dataclass(frozen=True, slots=True)
class RentReservation:
    required_lamports: int
    reserved_lamports: int
    peak_locked_lamports: int

    def assert_sufficient(self) -> None:
        if self.reserved_lamports < self.required_lamports:
            raise AccountLifecycleError(
                AccountLifecycleReason.INSUFFICIENT_RENT_RESERVATION,
                "reserved rent is below required rent",
                details={
                    "required_lamports": self.required_lamports,
                    "reserved_lamports": self.reserved_lamports,
                },
            )
        if self.peak_locked_lamports < self.reserved_lamports:
            raise AccountLifecycleError(
                AccountLifecycleReason.INSUFFICIENT_RENT_RESERVATION,
                "peak locked rent must cover reserved rent",
            )


@dataclass(frozen=True, slots=True)
class AssociatedTokenAccountPolicy:
    owner: str
    mint: str
    token_program: str
    payer: str
    rent: RentEvidence
    create_idempotent: bool
    account_data_size: int = TOKEN_ACCOUNT_BASE_DATA_SIZE

    def __post_init__(self) -> None:
        _parse_pubkey(self.owner)
        _parse_pubkey(self.mint)
        _parse_pubkey(self.token_program)
        _parse_pubkey(self.payer)
        if self.account_data_size != self.rent.data_size:
            raise AccountLifecycleError(
                AccountLifecycleReason.INSUFFICIENT_RENT_RESERVATION,
                "rent evidence size must match token account size",
            )

    @property
    def expected_ata(self) -> str:
        return derive_associated_token_address(
            self.owner,
            self.mint,
            self.token_program,
        )


@dataclass(frozen=True, slots=True)
class AssociatedTokenAccountEvidence:
    address: str
    owner: str
    mint: str
    token_program: str
    exists: bool
    pre_existing: bool
    lamports: int = 0

    def __post_init__(self) -> None:
        _parse_pubkey(self.address)
        _parse_pubkey(self.owner)
        _parse_pubkey(self.mint)
        _parse_pubkey(self.token_program)


@dataclass(frozen=True, slots=True)
class InstructionLifecycleEffect:
    stage: LifecycleStage
    debits_payer_lamports: int = 0
    reserved_lamports: int = 0
    uses_flash_principal: bool = False
    description: str = ""


@dataclass(frozen=True, slots=True)
class WsolLifecyclePolicy:
    account: str
    funding_source: WsolFundingSource
    amount_lamports: int
    rent_lamports: int
    sync_native_after_funding: bool
    temporary_account: bool
    pre_existing: bool
    close_destination: str
    close_authority: str
    cleanup_stage: LifecycleStage = LifecycleStage.POST_REPAY_CLEANUP

    def __post_init__(self) -> None:
        _parse_pubkey(self.account)
        _parse_pubkey(self.close_destination)
        _parse_pubkey(self.close_authority)
        if self.amount_lamports < 0 or self.rent_lamports < 0:
            raise AccountLifecycleError(
                AccountLifecycleReason.INVALID_JUPITER_LIFECYCLE_FIELD,
                "wSOL amount and rent must be non-negative",
            )


@dataclass(frozen=True, slots=True)
class CleanupPolicy:
    account: str
    pre_existing: bool
    close_destination: str
    expected_rent_destination: str
    authority_change: bool = False

    def __post_init__(self) -> None:
        _parse_pubkey(self.account)
        _parse_pubkey(self.close_destination)
        _parse_pubkey(self.expected_rent_destination)


@dataclass(frozen=True, slots=True)
class LegAccountPlan:
    leg_id: str
    ata_addresses: tuple[str, ...] = ()
    cleanup_accounts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for value in (*self.ata_addresses, *self.cleanup_accounts):
            _parse_pubkey(value)


def require_explicit_jupiter_lifecycle_params(
    payload: Mapping[str, object],
) -> JupiterLifecycleParams:
    missing = [
        key
        for key in (
            "inputMint",
            "outputMint",
            "amount",
            "taker",
            "payer",
            "slippageBps",
            "wrapAndUnwrapSol",
            "maxAccounts",
            "blockhashSlotsToExpiry",
            "forJitoBundle",
            "swapMode",
        )
        if key not in payload
    ]
    if missing:
        raise AccountLifecycleError(
            AccountLifecycleReason.IMPLICIT_JUPITER_DEFAULT,
            "Jupiter lifecycle request must not rely on provider defaults",
            details={"missing": tuple(missing)},
        )
    return JupiterLifecycleParams(
        input_mint=_string(payload["inputMint"], "inputMint"),
        output_mint=_string(payload["outputMint"], "outputMint"),
        amount=_int(payload["amount"], "amount"),
        taker=_string(payload["taker"], "taker"),
        payer=_string(payload["payer"], "payer"),
        slippage_bps=_int(payload["slippageBps"], "slippageBps"),
        wrap_and_unwrap_sol=_bool(payload["wrapAndUnwrapSol"], "wrapAndUnwrapSol"),
        max_accounts=_int(payload["maxAccounts"], "maxAccounts"),
        blockhash_slots_to_expiry=_int(
            payload["blockhashSlotsToExpiry"],
            "blockhashSlotsToExpiry",
        ),
        for_jito_bundle=_bool(payload["forJitoBundle"], "forJitoBundle"),
        swap_mode=_string(payload["swapMode"], "swapMode"),
        destination_token_account=_optional_string(
            payload.get("destinationTokenAccount"),
            "destinationTokenAccount",
        ),
        native_destination_account=_optional_string(
            payload.get("nativeDestinationAccount"),
            "nativeDestinationAccount",
        ),
    )


def derive_associated_token_address(
    owner: str,
    mint: str,
    token_program: str = SPL_TOKEN_PROGRAM_ID,
) -> str:
    owner_key = _parse_pubkey(owner)
    mint_key = _parse_pubkey(mint)
    token_key = _parse_pubkey(token_program)
    address, _ = Pubkey.find_program_address(
        [bytes(owner_key), bytes(token_key), bytes(mint_key)],
        _parse_pubkey(ASSOCIATED_TOKEN_PROGRAM_ID),
    )
    return str(address)


def validate_associated_token_account(
    policy: AssociatedTokenAccountPolicy,
    evidence: AssociatedTokenAccountEvidence,
    reservation: RentReservation,
) -> AccountLifecycleFinding:
    if evidence.address != policy.expected_ata:
        raise AccountLifecycleError(
            AccountLifecycleReason.ATA_ADDRESS_MISMATCH,
            "associated token account address does not match owner/mint/program PDA",
        )
    if evidence.owner != policy.owner:
        raise AccountLifecycleError(
            AccountLifecycleReason.ATA_OWNER_MISMATCH,
            "associated token account owner does not match policy",
        )
    if evidence.mint != policy.mint:
        raise AccountLifecycleError(
            AccountLifecycleReason.ATA_MINT_MISMATCH,
            "associated token account mint does not match policy",
        )
    if evidence.token_program != policy.token_program:
        raise AccountLifecycleError(
            AccountLifecycleReason.ATA_TOKEN_PROGRAM_MISMATCH,
            "associated token account token program does not match policy",
        )
    if not evidence.exists and not policy.create_idempotent:
        raise AccountLifecycleError(
            AccountLifecycleReason.ATA_CREATE_NOT_IDEMPOTENT,
            "missing ATA requires explicit idempotent create policy",
        )
    if not evidence.exists:
        reservation.assert_sufficient()
    return AccountLifecycleFinding(
        semantic_class="existing_ata" if evidence.exists else "idempotent_ata_create",
        account=evidence.address,
        lamports_reserved=0 if evidence.exists else reservation.reserved_lamports,
        stage=LifecycleStage.ROUTE_SETUP,
    )


def validate_instruction_lifecycle_effect(
    effect: InstructionLifecycleEffect,
) -> AccountLifecycleFinding:
    if (
        effect.stage is LifecycleStage.PRE_BORROW_OWN_CAPITAL
        and effect.uses_flash_principal
    ):
        raise AccountLifecycleError(
            AccountLifecycleReason.FLASH_PRINCIPAL_PRE_BORROW,
            "flash principal cannot fund pre-borrow setup",
        )
    if effect.debits_payer_lamports > effect.reserved_lamports:
        raise AccountLifecycleError(
            AccountLifecycleReason.PRE_BORROW_PAYER_DEBIT,
            "payer debit is not covered by reservation",
            details={
                "debits_payer_lamports": effect.debits_payer_lamports,
                "reserved_lamports": effect.reserved_lamports,
            },
        )
    return AccountLifecycleFinding(
        semantic_class="reserved_instruction_effect",
        account="",
        lamports_reserved=effect.reserved_lamports,
        stage=effect.stage,
    )


def validate_wsol_lifecycle(
    policy: WsolLifecyclePolicy,
    *,
    payer: str,
) -> AccountLifecycleFinding:
    payer = str(_parse_pubkey(payer))
    if policy.amount_lamports > 0 and not policy.sync_native_after_funding:
        raise AccountLifecycleError(
            AccountLifecycleReason.WSOL_SYNC_MISSING,
            "wSOL funding must be followed by SyncNative",
        )
    if policy.temporary_account and policy.pre_existing:
        raise AccountLifecycleError(
            AccountLifecycleReason.CLEANUP_PREEXISTING_ACCOUNT,
            "temporary cleanup must not close a pre-existing token account",
        )
    if policy.temporary_account and policy.close_destination != payer:
        raise AccountLifecycleError(
            AccountLifecycleReason.WSOL_CLOSE_DESTINATION,
            "temporary wSOL close destination must be the payer",
        )
    if policy.close_authority != payer:
        raise AccountLifecycleError(
            AccountLifecycleReason.CLEANUP_AUTHORITY_CHANGE,
            "wSOL close authority must remain the payer",
        )
    return AccountLifecycleFinding(
        semantic_class=(
            "temporary_wsol" if policy.temporary_account else "persistent_wsol"
        ),
        account=policy.account,
        lamports_reserved=policy.rent_lamports,
        stage=policy.cleanup_stage,
    )


def validate_cleanup_policy(policy: CleanupPolicy) -> AccountLifecycleFinding:
    if policy.pre_existing:
        raise AccountLifecycleError(
            AccountLifecycleReason.CLEANUP_PREEXISTING_ACCOUNT,
            "cleanup must not close a pre-existing user account",
        )
    if policy.close_destination != policy.expected_rent_destination:
        raise AccountLifecycleError(
            AccountLifecycleReason.WSOL_CLOSE_DESTINATION,
            "cleanup rent destination does not match policy",
        )
    if policy.authority_change:
        raise AccountLifecycleError(
            AccountLifecycleReason.CLEANUP_AUTHORITY_CHANGE,
            "cleanup must not alter authority",
        )
    return AccountLifecycleFinding(
        semantic_class="cleanup_allowed",
        account=policy.account,
        stage=LifecycleStage.POST_REPAY_CLEANUP,
    )


def validate_two_leg_lifecycle_dedup(
    first: LegAccountPlan,
    second: LegAccountPlan,
) -> AccountLifecycleFinding:
    duplicate_atas = set(first.ata_addresses).intersection(second.ata_addresses)
    if duplicate_atas:
        raise AccountLifecycleError(
            AccountLifecycleReason.DUPLICATE_ATA_PLAN,
            "two legs must share one deduplicated ATA plan",
            details={"addresses": tuple(sorted(duplicate_atas))},
        )
    duplicate_cleanup = set(first.cleanup_accounts).intersection(
        second.cleanup_accounts
    )
    if duplicate_cleanup:
        raise AccountLifecycleError(
            AccountLifecycleReason.CONFLICTING_CLEANUP,
            "two legs must not both cleanup the same account",
            details={"addresses": tuple(sorted(duplicate_cleanup))},
        )
    return AccountLifecycleFinding(
        semantic_class="two_leg_lifecycle_deduped",
        account="",
    )


def _parse_pubkey(value: str) -> Pubkey:
    try:
        return Pubkey.from_string(value)
    except Exception as exc:
        raise AccountLifecycleError(
            AccountLifecycleReason.INVALID_PUBKEY,
            "value is not a valid Solana pubkey",
        ) from exc


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise AccountLifecycleError(
            AccountLifecycleReason.INVALID_JUPITER_LIFECYCLE_FIELD,
            f"{label} must be a non-empty string",
        )
    return value


def _optional_string(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _string(value, label)


def _int(value: object, label: str) -> int:
    if isinstance(value, bool):
        raise AccountLifecycleError(
            AccountLifecycleReason.INVALID_JUPITER_LIFECYCLE_FIELD,
            f"{label} must be an integer",
        )
    try:
        result = int(value)
    except Exception as exc:
        raise AccountLifecycleError(
            AccountLifecycleReason.INVALID_JUPITER_LIFECYCLE_FIELD,
            f"{label} must be an integer",
        ) from exc
    return result


def _bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise AccountLifecycleError(
            AccountLifecycleReason.INVALID_JUPITER_LIFECYCLE_FIELD,
            f"{label} must be boolean",
        )
    return value


def _lower_bool(value: bool) -> str:
    return "true" if value else "false"


__all__ = [
    "ASSOCIATED_TOKEN_PROGRAM_ID",
    "NATIVE_SOL_MINT",
    "SPL_TOKEN_PROGRAM_ID",
    "SYSTEM_PROGRAM_ID",
    "TOKEN_2022_PROGRAM_ID",
    "TOKEN_ACCOUNT_BASE_DATA_SIZE",
    "AccountLifecycleError",
    "AccountLifecycleFinding",
    "AccountLifecycleReason",
    "AssociatedTokenAccountEvidence",
    "AssociatedTokenAccountPolicy",
    "CleanupPolicy",
    "InstructionLifecycleEffect",
    "JupiterLifecycleParams",
    "LegAccountPlan",
    "LifecycleStage",
    "RentEvidence",
    "RentReservation",
    "WsolFundingSource",
    "WsolLifecyclePolicy",
    "derive_associated_token_address",
    "require_explicit_jupiter_lifecycle_params",
    "validate_associated_token_account",
    "validate_cleanup_policy",
    "validate_instruction_lifecycle_effect",
    "validate_two_leg_lifecycle_dedup",
    "validate_wsol_lifecycle",
]
