"""PR-114 semantic firewall for untrusted provider instructions.

Program-id allowlisting is necessary but insufficient. Provider artifacts can use
allowed programs to encode dangerous semantics such as token authority changes,
account closes, arbitrary system transfers, or Token-2022 extension behavior.
This module is sender-free: it only validates instruction artifacts.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Mapping

from solders.pubkey import Pubkey

from src.providers.jupiter.router import JupiterInstructionBundle, JupiterRawInstruction

SYSTEM_PROGRAM_ID = "11111111111111111111111111111111"
SPL_TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM_ID = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
ASSOCIATED_TOKEN_PROGRAM_ID = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"

_FORBIDDEN_TOKEN_TAGS = frozenset({4, 6, 7, 8, 9, 14, 15, 16})
_FORBIDDEN_TEXT_MARKERS = frozenset(
    {
        "approve",
        "burn",
        "closeaccount",
        "delegate",
        "drain",
        "mintto",
        "setauthority",
        "transferhook",
    }
)


class InstructionRole(StrEnum):
    SETUP = "setup"
    OTHER = "other"
    SWAP = "swap"
    CLEANUP = "cleanup"


class InstructionFirewallReason(StrEnum):
    INVALID_PUBKEY = "pr114_invalid_pubkey"
    INVALID_DATA = "pr114_invalid_data"
    UNEXPECTED_SIGNER = "pr114_unexpected_signer"
    WRITABLE_PAYER_FORBIDDEN = "pr114_writable_payer_forbidden"
    DANGEROUS_TEXT_MARKER = "pr114_dangerous_text_marker"
    DANGEROUS_TOKEN_INSTRUCTION = "pr114_dangerous_token_instruction"
    TOKEN_2022_UNSUPPORTED = "pr114_token_2022_unsupported"
    SYSTEM_TRANSFER_FORBIDDEN = "pr114_system_transfer_forbidden"
    ASSOCIATED_TOKEN_SCHEMA = "pr114_associated_token_schema"
    PROVIDER_COMPUTE_OR_TIP = "pr114_provider_compute_or_tip"


class InstructionFirewallError(ValueError):
    def __init__(
        self,
        reason: InstructionFirewallReason,
        message: str,
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(f"{reason.value}: {message}")
        self.reason = reason
        self.details = dict(details or {})


@dataclass(frozen=True, slots=True)
class InstructionFirewallPolicy:
    payer: str
    allowed_payer_signers: tuple[str, ...] = ()
    allow_token_2022: bool = False
    allowed_system_tags: tuple[int, ...] = ()
    jupiter_program_ids: tuple[str, ...] = ()
    forbidden_wallet_owned_accounts: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        values = (
            self.payer,
            *self.allowed_payer_signers,
            *self.jupiter_program_ids,
            *self.forbidden_wallet_owned_accounts,
        )
        for value in values:
            _parse_pubkey(value)

    @property
    def signer_allowlist(self) -> frozenset[str]:
        return frozenset((self.payer, *self.allowed_payer_signers))

    @property
    def wallet_owned_forbidden(self) -> frozenset[str]:
        return frozenset((self.payer, *self.forbidden_wallet_owned_accounts))


@dataclass(frozen=True, slots=True)
class InstructionFirewallFinding:
    role: InstructionRole
    program_id: str
    account_count: int
    data_length: int
    semantic_class: str


def validate_jupiter_instruction_bundle(
    bundle: JupiterInstructionBundle,
    policy: InstructionFirewallPolicy,
) -> tuple[InstructionFirewallFinding, ...]:
    if bundle.compute_unit_price_instructions or bundle.tip_instruction is not None:
        raise InstructionFirewallError(
            InstructionFirewallReason.PROVIDER_COMPUTE_OR_TIP,
            "provider-owned compute budget and tip instructions are forbidden",
        )

    cleanup = () if bundle.cleanup_instruction is None else (bundle.cleanup_instruction,)
    buckets = (
        (InstructionRole.SETUP, bundle.setup_instructions),
        (InstructionRole.OTHER, bundle.other_instructions),
        (InstructionRole.SWAP, (bundle.swap_instruction,)),
        (InstructionRole.CLEANUP, cleanup),
    )
    return tuple(
        validate_raw_provider_instruction(instruction, policy, role=role, index=index)
        for role, instructions in buckets
        for index, instruction in enumerate(instructions)
    )


def validate_raw_provider_instruction(
    instruction: JupiterRawInstruction,
    policy: InstructionFirewallPolicy,
    *,
    role: InstructionRole,
    index: int = 0,
) -> InstructionFirewallFinding:
    program_id = _parse_pubkey(instruction.program_id)
    data = _decode_data(instruction)

    for account_index, account in enumerate(instruction.accounts):
        account_pubkey = _parse_pubkey(account.pubkey)
        details = {"role": role.value, "index": index, "account_index": account_index}
        if account.is_signer and account_pubkey not in policy.signer_allowlist:
            raise InstructionFirewallError(
                InstructionFirewallReason.UNEXPECTED_SIGNER,
                "provider instruction requires an undeclared signer",
                details=details,
            )
        if account.is_writable and account_pubkey in policy.wallet_owned_forbidden:
            raise InstructionFirewallError(
                InstructionFirewallReason.WRITABLE_PAYER_FORBIDDEN,
                "provider instruction marks a wallet-owned account writable",
                details=details,
            )

    _reject_dangerous_text(instruction.name, data, role=role, index=index)
    semantic_class = _semantic_class(program_id, data, policy, role=role, index=index)
    return InstructionFirewallFinding(
        role=role,
        program_id=program_id,
        account_count=len(instruction.accounts),
        data_length=len(data),
        semantic_class=semantic_class,
    )


def _decode_data(instruction: JupiterRawInstruction) -> bytes:
    try:
        return base64.b64decode(instruction.data_b64, validate=True)
    except Exception as exc:
        raise InstructionFirewallError(
            InstructionFirewallReason.INVALID_DATA,
            "provider instruction data is not canonical base64",
        ) from exc


def _parse_pubkey(value: str) -> str:
    try:
        return str(Pubkey.from_string(value))
    except Exception as exc:
        raise InstructionFirewallError(
            InstructionFirewallReason.INVALID_PUBKEY,
            "value is not a valid Solana pubkey",
        ) from exc


def _reject_dangerous_text(
    name: str,
    data: bytes,
    *,
    role: InstructionRole,
    index: int,
) -> None:
    decoded = data.decode("utf-8", errors="ignore")
    text = _normalize_text(name) + _normalize_text(decoded)
    for marker in _FORBIDDEN_TEXT_MARKERS:
        if marker in text:
            raise InstructionFirewallError(
                InstructionFirewallReason.DANGEROUS_TEXT_MARKER,
                "provider instruction contains a forbidden semantic marker",
                details={"role": role.value, "index": index, "marker": marker},
            )


def _normalize_text(value: str) -> str:
    return "".join(char for char in value.lower() if char.isalnum())


def _semantic_class(
    program_id: str,
    data: bytes,
    policy: InstructionFirewallPolicy,
    *,
    role: InstructionRole,
    index: int,
) -> str:
    if program_id == TOKEN_2022_PROGRAM_ID and not policy.allow_token_2022:
        raise InstructionFirewallError(
            InstructionFirewallReason.TOKEN_2022_UNSUPPORTED,
            "Token-2022 instructions require an explicit extension policy",
            details={"role": role.value, "index": index},
        )
    if program_id in {SPL_TOKEN_PROGRAM_ID, TOKEN_2022_PROGRAM_ID}:
        return _token_semantics(data, role=role, index=index)
    if program_id == SYSTEM_PROGRAM_ID:
        return _system_semantics(data, policy, role=role, index=index)
    if program_id == ASSOCIATED_TOKEN_PROGRAM_ID:
        return _ata_semantics(data, role=role, index=index)
    if program_id in policy.jupiter_program_ids:
        return "jupiter-pinned-program"
    return "opaque-provider-program"


def _token_semantics(data: bytes, *, role: InstructionRole, index: int) -> str:
    if not data:
        raise InstructionFirewallError(
            InstructionFirewallReason.INVALID_DATA,
            "token instruction data must include a discriminator",
            details={"role": role.value, "index": index},
        )
    tag = data[0]
    if tag in _FORBIDDEN_TOKEN_TAGS:
        raise InstructionFirewallError(
            InstructionFirewallReason.DANGEROUS_TOKEN_INSTRUCTION,
            "token authority/delegate/mint/burn/close instruction is forbidden",
            details={"role": role.value, "index": index, "tag": tag},
        )
    return f"token-tag-{tag}"


def _system_semantics(
    data: bytes,
    policy: InstructionFirewallPolicy,
    *,
    role: InstructionRole,
    index: int,
) -> str:
    if len(data) < 4:
        raise InstructionFirewallError(
            InstructionFirewallReason.INVALID_DATA,
            "system instruction data must include a 4-byte discriminator",
            details={"role": role.value, "index": index},
        )
    tag = int.from_bytes(data[:4], "little")
    if tag == 2 or tag not in policy.allowed_system_tags:
        raise InstructionFirewallError(
            InstructionFirewallReason.SYSTEM_TRANSFER_FORBIDDEN,
            "provider-owned system transfer/tag is forbidden",
            details={"role": role.value, "index": index, "tag": tag},
        )
    return f"system-tag-{tag}"


def _ata_semantics(data: bytes, *, role: InstructionRole, index: int) -> str:
    if len(data) > 1:
        raise InstructionFirewallError(
            InstructionFirewallReason.ASSOCIATED_TOKEN_SCHEMA,
            "ATA instruction data has an unsupported discriminator shape",
            details={"role": role.value, "index": index},
        )
    return "associated-token-create"


__all__ = [
    "ASSOCIATED_TOKEN_PROGRAM_ID",
    "InstructionFirewallError",
    "InstructionFirewallFinding",
    "InstructionFirewallPolicy",
    "InstructionFirewallReason",
    "InstructionRole",
    "SPL_TOKEN_PROGRAM_ID",
    "SYSTEM_PROGRAM_ID",
    "TOKEN_2022_PROGRAM_ID",
    "validate_jupiter_instruction_bundle",
    "validate_raw_provider_instruction",
]
