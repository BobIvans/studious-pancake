"""PR-115 simulation-owned pre/post state evidence.

This boundary derives economic observations from raw account evidence. It does
not accept caller-supplied native, token, MarginFi, or decoded-hash evidence,
and it never signs, submits, or calls RPC.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
from typing import Any, cast

from .exact_simulation import ExactSimulationReport

PR115_SCHEMA_VERSION = "pr115.simulation-owned-economic-proof.v2"
PR115_DECODER_VERSION = "pr115.decoder.native-legacy-spl-marginfi-d4c70.v2"
SYSTEM_PROGRAM_ID = "11111111111111111111111111111111"
SPL_TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM_ID = "TokenzQdBNbLqP5VEhdkAS6EPw1N1qEHxZC6kzNRQdB"
SPL_TOKEN_ACCOUNT_LEN = 165
SPL_TOKEN_MINT_OFFSET = 0
SPL_TOKEN_OWNER_OFFSET = 32
SPL_TOKEN_AMOUNT_OFFSET = 64
SPL_TOKEN_AMOUNT_LEN = 8


class PR115StateEvidenceError(ValueError):
    """Raised when raw state evidence cannot prove an economic observation."""


class PR115StateEvidenceCode(StrEnum):
    """Stable PR-115 fail-closed reason codes."""

    ADDRESS_SET_MISMATCH = "address_set_mismatch"
    CONTEXT_SLOT_VIOLATION = "context_slot_violation"
    COPIED_HASH_MISMATCH = "copied_hash_mismatch"
    DUPLICATE_ADDRESS = "duplicate_address"
    MALFORMED_ACCOUNT = "malformed_account"
    MISSING_ACCOUNT = "missing_account"
    UNEXPECTED_EXECUTABLE = "unexpected_executable"
    UNREQUESTED_ACCOUNT = "unrequested_account"
    UNSUPPORTED_ACCOUNT_OWNER = "unsupported_account_owner"
    UNSUPPORTED_TOKEN_2022 = "unsupported_token_2022"
    WRONG_DATA_LENGTH = "wrong_data_length"
    WRONG_OWNER = "wrong_owner"


@dataclass(frozen=True, slots=True)
class PR115MarginfiDecodePolicy:
    """Planner-bound first-cycle context; source-derived offline scope only."""

    source_commit: str
    layout_sha256: str
    margin_account: str
    group: str
    authority: str
    bank: str
    vault: str
    principal: int


@dataclass(frozen=True, slots=True)
class PR115MarginfiRepaymentState:
    """Narrow raw-state invariants, requiring separate atomic-message proof.

    Zero shares and vault movement alone do not prove borrow/swap execution.
    This is not deployed protocol qualification or realized settlement.
    """

    source_commit: str
    layout_sha256: str
    margin_account: str
    bank: str
    vault: str
    mint: str
    principal: int
    conservative_fee_amount: int
    pre_flags: int
    post_flags: int
    post_target_asset_shares: int
    post_target_liability_shares: int
    pre_vault_amount: int
    post_vault_amount: int
    pre_margin_raw_hash: str
    post_margin_raw_hash: str
    pre_bank_raw_hash: str
    post_bank_raw_hash: str
    program_id: str
    token_program: str
    mint_decimals: int
    pre_target_asset_shares: int
    pre_target_liability_shares: int


@dataclass(frozen=True, slots=True)
class PR115ReadonlyAccountBinding:
    """Approved non-economic input retained byte-for-byte across simulation.

    This preserves raw oracle inputs, not an oracle price interpretation.
    """

    address: str
    owner: str
    raw_sha256: str


@dataclass(frozen=True, slots=True)
class PR115DecodePolicy:
    """Strict decoder policy for simulation-owned evidence."""

    expected_owner_by_address: Mapping[str, str] | None = None
    allow_legacy_spl_token_accounts: bool = True
    allow_token_2022_accounts: bool = False
    allow_marginfi_accounts: bool = False
    max_account_data_bytes: int = 4096
    marginfi: PR115MarginfiDecodePolicy | None = None
    readonly_accounts: tuple[PR115ReadonlyAccountBinding, ...] = ()

    def __post_init__(self) -> None:
        if self.max_account_data_bytes <= 0:
            raise PR115StateEvidenceError("max_account_data_bytes must be positive")


@dataclass(frozen=True, slots=True)
class PR115RawAccountSnapshot:
    """One monitored account bound to address, index, owner, bytes, and hashes."""

    address: str
    index: int
    owner: str
    executable: bool
    lamports: int
    data_base64: str
    data_hash: str
    raw_hash: str
    decoded_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "address": self.address,
            "index": self.index,
            "owner": self.owner,
            "executable": self.executable,
            "lamports": self.lamports,
            "data_base64": self.data_base64,
            "data_hash": self.data_hash,
            "raw_hash": self.raw_hash,
            "decoded_hash": self.decoded_hash,
        }


@dataclass(frozen=True, slots=True)
class PR115NativeLamportDelta:
    """Native lamport delta derived only from raw pre/post account objects."""

    address: str
    pre_lamports: int
    post_lamports: int
    delta_lamports: int
    pre_raw_hash: str
    post_raw_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "address": self.address,
            "pre_lamports": self.pre_lamports,
            "post_lamports": self.post_lamports,
            "delta_lamports": self.delta_lamports,
            "pre_raw_hash": self.pre_raw_hash,
            "post_raw_hash": self.post_raw_hash,
        }


@dataclass(frozen=True, slots=True)
class PR115TokenAccountDelta:
    """Legacy SPL Token amount delta derived only from raw account bytes."""

    address: str
    mint_hash: str
    owner_hash: str
    pre_amount: int
    post_amount: int
    delta_amount: int
    pre_raw_hash: str
    post_raw_hash: str
    mint: str = ""
    authority: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "address": self.address,
            "mint_hash": self.mint_hash,
            "owner_hash": self.owner_hash,
            "pre_amount": self.pre_amount,
            "post_amount": self.post_amount,
            "delta_amount": self.delta_amount,
            "pre_raw_hash": self.pre_raw_hash,
            "post_raw_hash": self.post_raw_hash,
            "mint": self.mint,
            "authority": self.authority,
        }


@dataclass(frozen=True, slots=True)
class PR115SimulationOwnedEconomicProof:
    """Proof that deltas were decoded from raw evidence rather than caller data."""

    schema_version: str
    decoder_version: str
    message_hash: str
    simulation_response_hash: str
    monitored_accounts: tuple[str, ...]
    pre_state_slot: int
    post_state_slot: int
    pre_root_slot: int | None
    post_root_slot: int | None
    min_context_slot: int
    pre_state_hash: str
    post_state_hash: str
    raw_evidence_hash: str
    native_deltas: tuple[PR115NativeLamportDelta, ...]
    token_deltas: tuple[PR115TokenAccountDelta, ...]
    marginfi_repayment: PR115MarginfiRepaymentState | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "decoder_version": self.decoder_version,
            "message_hash": self.message_hash,
            "simulation_response_hash": self.simulation_response_hash,
            "monitored_accounts": list(self.monitored_accounts),
            "pre_state_slot": self.pre_state_slot,
            "post_state_slot": self.post_state_slot,
            "pre_root_slot": self.pre_root_slot,
            "post_root_slot": self.post_root_slot,
            "min_context_slot": self.min_context_slot,
            "pre_state_hash": self.pre_state_hash,
            "post_state_hash": self.post_state_hash,
            "raw_evidence_hash": self.raw_evidence_hash,
            "native_deltas": [item.to_dict() for item in self.native_deltas],
            "token_deltas": [item.to_dict() for item in self.token_deltas],
            "marginfi_repayment": (
                None
                if self.marginfi_repayment is None
                else asdict(self.marginfi_repayment)
            ),
        }


def build_pr115_proof_from_report(
    report: ExactSimulationReport,
    *,
    pre_state_accounts: Sequence[Mapping[str, Any] | None],
    pre_state_slot: int,
    pre_root_slot: int | None = None,
    post_root_slot: int | None = None,
    policy: PR115DecodePolicy | None = None,
) -> PR115SimulationOwnedEconomicProof:
    """Derive economic proof from exact simulation raw account evidence only."""

    post_state_accounts = getattr(report.final, "returned_accounts", None)
    if post_state_accounts is None:
        raise PR115StateEvidenceError("final simulation did not preserve raw accounts")
    typed_post_accounts = cast(
        Sequence[Mapping[str, Any] | None],
        post_state_accounts,
    )
    return build_pr115_simulation_owned_economic_proof(
        monitored_accounts=report.monitored_accounts,
        pre_state_accounts=pre_state_accounts,
        post_state_accounts=typed_post_accounts,
        message_hash=report.message_hash,
        simulation_response_hash=report.final.response_hash,
        pre_state_slot=pre_state_slot,
        post_state_slot=report.final.slot,
        min_context_slot=report.min_context_slot,
        pre_root_slot=pre_root_slot,
        post_root_slot=post_root_slot,
        expected_post_account_hashes=report.final.returned_account_hashes,
        policy=policy,
    )


def build_pr115_simulation_owned_economic_proof(
    *,
    monitored_accounts: Sequence[str],
    pre_state_accounts: Sequence[Mapping[str, Any] | None],
    post_state_accounts: Sequence[Mapping[str, Any] | None],
    message_hash: str,
    simulation_response_hash: str,
    pre_state_slot: int,
    post_state_slot: int,
    min_context_slot: int,
    pre_root_slot: int | None = None,
    post_root_slot: int | None = None,
    expected_post_account_hashes: Sequence[str] | None = None,
    policy: PR115DecodePolicy | None = None,
) -> PR115SimulationOwnedEconomicProof:
    """Build a PR-115 proof without accepting caller-supplied observations."""

    active_policy = policy or PR115DecodePolicy()
    addresses = tuple(str(address) for address in monitored_accounts)
    _validate_addresses(addresses)
    _validate_slots(
        pre_state_slot=pre_state_slot,
        post_state_slot=post_state_slot,
        min_context_slot=min_context_slot,
        pre_root_slot=pre_root_slot,
        post_root_slot=post_root_slot,
    )
    if len(pre_state_accounts) != len(addresses):
        raise PR115StateEvidenceError(PR115StateEvidenceCode.ADDRESS_SET_MISMATCH)
    if len(post_state_accounts) != len(addresses):
        raise PR115StateEvidenceError(PR115StateEvidenceCode.UNREQUESTED_ACCOUNT)

    pre_snapshots = tuple(
        _decode_snapshot(address, index, account, active_policy)
        for index, (address, account) in enumerate(zip(addresses, pre_state_accounts))
    )
    post_snapshots = tuple(
        _decode_snapshot(address, index, account, active_policy)
        for index, (address, account) in enumerate(zip(addresses, post_state_accounts))
    )
    _validate_expected_hashes(expected_post_account_hashes, post_snapshots)
    readonly = {item.address: item for item in active_policy.readonly_accounts}
    if len(readonly) != len(active_policy.readonly_accounts):
        raise PR115StateEvidenceError("duplicate_readonly_account")
    if not set(readonly).issubset(addresses):
        raise PR115StateEvidenceError("missing_readonly_account")
    for pre, post in zip(pre_snapshots, post_snapshots):
        binding = readonly.get(post.address)
        if binding is not None and not (
            pre.owner == post.owner == binding.owner
            and pre.raw_hash == post.raw_hash == binding.raw_sha256
        ):
            raise PR115StateEvidenceError("readonly_account_changed")
    repayment = (
        None
        if active_policy.marginfi is None
        else _decode_marginfi_repayment(
            pre_snapshots, post_snapshots, active_policy.marginfi
        )
    )

    native_deltas: list[PR115NativeLamportDelta] = []
    token_deltas: list[PR115TokenAccountDelta] = []
    for pre, post in zip(pre_snapshots, post_snapshots):
        if pre.owner != post.owner:
            raise PR115StateEvidenceError(PR115StateEvidenceCode.WRONG_OWNER)
        if post.owner == SYSTEM_PROGRAM_ID:
            native_deltas.append(_native_delta(pre, post))
        elif post.owner == SPL_TOKEN_PROGRAM_ID:
            if not active_policy.allow_legacy_spl_token_accounts:
                raise PR115StateEvidenceError(
                    PR115StateEvidenceCode.UNSUPPORTED_ACCOUNT_OWNER
                )
            token_deltas.append(_token_delta(pre, post))
        elif post.owner == TOKEN_2022_PROGRAM_ID:
            raise PR115StateEvidenceError(PR115StateEvidenceCode.UNSUPPORTED_TOKEN_2022)
        elif (
            repayment is not None
            and active_policy.marginfi is not None
            and post.address
            in {
                active_policy.marginfi.margin_account,
                active_policy.marginfi.bank,
                active_policy.marginfi.group,
            }
        ):
            pass  # Already decoded and identity checked by the narrow protocol owner.
        elif post.address in readonly:
            pass  # Exact raw preservation, never interpreted as money or price.
        else:
            raise PR115StateEvidenceError(
                PR115StateEvidenceCode.UNSUPPORTED_ACCOUNT_OWNER
            )

    pre_state_hash = _hash_json([item.to_dict() for item in pre_snapshots])
    post_state_hash = _hash_json([item.to_dict() for item in post_snapshots])
    raw_evidence_hash = _hash_json(
        {
            "message_hash": message_hash,
            "simulation_response_hash": simulation_response_hash,
            "pre_state_hash": pre_state_hash,
            "post_state_hash": post_state_hash,
            "pre_state_slot": pre_state_slot,
            "post_state_slot": post_state_slot,
            "pre_root_slot": pre_root_slot,
            "post_root_slot": post_root_slot,
            "min_context_slot": min_context_slot,
            "decoder_version": PR115_DECODER_VERSION,
            "marginfi_repayment": None if repayment is None else asdict(repayment),
        }
    )
    return PR115SimulationOwnedEconomicProof(
        schema_version=PR115_SCHEMA_VERSION,
        decoder_version=PR115_DECODER_VERSION,
        message_hash=message_hash,
        simulation_response_hash=simulation_response_hash,
        monitored_accounts=addresses,
        pre_state_slot=pre_state_slot,
        post_state_slot=post_state_slot,
        pre_root_slot=pre_root_slot,
        post_root_slot=post_root_slot,
        min_context_slot=min_context_slot,
        pre_state_hash=pre_state_hash,
        post_state_hash=post_state_hash,
        raw_evidence_hash=raw_evidence_hash,
        native_deltas=tuple(native_deltas),
        token_deltas=tuple(token_deltas),
        marginfi_repayment=repayment,
    )


def _decode_marginfi_repayment(
    before: Sequence[PR115RawAccountSnapshot],
    after: Sequence[PR115RawAccountSnapshot],
    context: PR115MarginfiDecodePolicy,
) -> PR115MarginfiRepaymentState:
    from solders.pubkey import Pubkey
    from src.providers.marginfi.accounts import (
        MARGINFI_SHARES_SOURCE_COMMIT,
        RpcAccount,
        decode_marginfi_balance_shares,
    )
    from src.providers.marginfi.errors import MarginfiRejection
    from src.providers.marginfi.layouts import (
        decode_margin_account,
        decode_bank,
        decode_group,
        decode_token_account,
        ceil_i80f48_product,
    )
    from src.providers.marginfi.pin import load_marginfi_contract_pin

    def require(condition: bool, reason: str) -> None:
        if not condition:
            raise PR115StateEvidenceError("marginfi_" + reason)

    require(
        type(context.principal) is int and 0 < context.principal < 2**64,
        "principal_invalid",
    )
    pin = load_marginfi_contract_pin()
    require(
        context.source_commit == pin.source_commit == MARGINFI_SHARES_SOURCE_COMMIT,
        "source_mismatch",
    )
    require(context.layout_sha256 == _hash_json(pin.raw), "layout_mismatch")
    addresses = (context.margin_account, context.bank, context.group, context.vault)
    require(len(set(addresses)) == 4, "address_alias")
    try:
        for address in (*addresses, context.authority):
            Pubkey.from_string(address)
    except ValueError as exc:
        raise PR115StateEvidenceError("marginfi_address_invalid") from exc
    pre = {item.address: item for item in before}
    post = {item.address: item for item in after}
    require(
        all(address in pre and address in post for address in addresses),
        "missing_account",
    )
    require(
        all(pre[address].lamports == post[address].lamports for address in addresses),
        "unsupported_protocol_rent_change",
    )

    def account(snapshot: PR115RawAccountSnapshot) -> RpcAccount:
        return RpcAccount(
            snapshot.address,
            snapshot.owner,
            _decode_snapshot_data(snapshot),
            snapshot.lamports,
            snapshot.executable,
        )

    try:
        margins = [
            decode_margin_account(account(states[context.margin_account]), pin)
            for states in (pre, post)
        ]
        balances = [
            decode_marginfi_balance_shares(account(states[context.margin_account]), pin)
            for states in (pre, post)
        ]
        banks = [
            decode_bank(account(states[context.bank]), pin, bank_address=context.bank)
            for states in (pre, post)
        ]
        # No wall-clock expiry inference: a set pause bit is unsupported here.
        require(
            all(
                _decode_snapshot_data(states[context.group])[8 + 248] & 1 == 0
                for states in (pre, post)
            ),
            "group_paused",
        )
        groups = [
            decode_group(account(states[context.group]), pin, now_timestamp=0)
            for states in (pre, post)
        ]
        require(not any(group.paused for group in groups), "group_paused")
        require(
            pre[context.group].data_hash == post[context.group].data_hash,
            "group_changed",
        )
        for margin in margins:
            require(
                margin.group == context.group and margin.authority == context.authority,
                "margin_identity_mismatch",
            )
            require(margin.account_flags == 0, "unsafe_account_flags")
        require(
            context.bank not in margins[0].active_balances, "preexisting_target_balance"
        )
        for positions in balances:
            for position in positions:
                if position.bank == context.bank:
                    require(
                        position.asset_shares == position.liability_shares == 0,
                        "target_shares_not_cleared",
                    )
        unrelated = [
            {
                position.bank: position.raw
                for position in positions
                if position.active and position.bank != context.bank
            }
            for positions in balances
        ]
        require(unrelated[0] == unrelated[1], "unrelated_position_changed")
        require(banks[0] == banks[1], "bank_configuration_changed")
        bank = banks[0]
        require(
            bank.group == context.group and bank.liquidity_vault == context.vault,
            "bank_identity_mismatch",
        )
        require(
            bank.operational_state == 1 and bank.token_program == SPL_TOKEN_PROGRAM_ID,
            "unsupported_bank",
        )
        # Bank share values at body offsets 72/88, repr(C) source d4c70c84.
        values = []
        for states in (pre, post):
            data = _decode_snapshot_data(states[context.bank])
            values.append(
                tuple(
                    int.from_bytes(
                        data[8 + offset : 8 + offset + 16], "little", signed=True
                    )
                    for offset in (72, 88)
                )
            )
        require(
            values[0] == values[1] and all(value > 0 for value in values[0]),
            "invalid_bank_share_values",
        )
        vaults = [
            decode_token_account(
                account(states[context.vault]),
                token_program=bank.token_program,
                expected_mint=bank.mint,
            )
            for states in (pre, post)
        ]
        require(
            all(vault.authority == bank.liquidity_vault_authority for vault in vaults),
            "vault_authority_mismatch",
        )
        vault_bytes = [
            _decode_snapshot_data(states[context.vault]) for states in (pre, post)
        ]
        require(
            vault_bytes[0][:64] + vault_bytes[0][72:]
            == vault_bytes[1][:64] + vault_bytes[1][72:],
            "vault_configuration_changed",
        )
        require(
            all(
                len(_decode_snapshot_data(states[context.vault])) == 165
                and _decode_snapshot_data(states[context.vault])[108] == 1
                for states in (pre, post)
            ),
            "unsupported_vault_layout",
        )
        fee = ceil_i80f48_product(context.principal, bank.origination_fee_raw_i80f48)
        require(vaults[0].amount >= context.principal, "insufficient_vault_principal")
        require(vaults[1].amount - vaults[0].amount >= fee, "vault_fee_not_returned")
    except MarginfiRejection as exc:
        raise PR115StateEvidenceError("marginfi_decode_rejected: " + str(exc)) from exc
    return PR115MarginfiRepaymentState(
        context.source_commit,
        context.layout_sha256,
        context.margin_account,
        context.bank,
        context.vault,
        bank.mint,
        context.principal,
        fee,
        margins[0].account_flags,
        margins[1].account_flags,
        0,
        0,
        vaults[0].amount,
        vaults[1].amount,
        pre[context.margin_account].raw_hash,
        post[context.margin_account].raw_hash,
        pre[context.bank].raw_hash,
        post[context.bank].raw_hash,
        pin.program_id,
        bank.token_program,
        bank.mint_decimals,
        0,
        0,
    )


def _validate_expected_hashes(
    expected_post_account_hashes: Sequence[str] | None,
    post_snapshots: Sequence[PR115RawAccountSnapshot],
) -> None:
    if expected_post_account_hashes is None:
        return
    expected = tuple(expected_post_account_hashes)
    actual = tuple(snapshot.raw_hash for snapshot in post_snapshots)
    if expected != actual:
        raise PR115StateEvidenceError(PR115StateEvidenceCode.COPIED_HASH_MISMATCH)


def _decode_snapshot(
    address: str,
    index: int,
    account: Mapping[str, Any] | None,
    policy: PR115DecodePolicy,
) -> PR115RawAccountSnapshot:
    if account is None:
        raise PR115StateEvidenceError(PR115StateEvidenceCode.MISSING_ACCOUNT)
    owner = account.get("owner")
    executable = account.get("executable")
    lamports = account.get("lamports")
    if not isinstance(owner, str) or not owner.strip():
        raise PR115StateEvidenceError(PR115StateEvidenceCode.MALFORMED_ACCOUNT)
    if not isinstance(executable, bool):
        raise PR115StateEvidenceError(PR115StateEvidenceCode.MALFORMED_ACCOUNT)
    if executable:
        raise PR115StateEvidenceError(PR115StateEvidenceCode.UNEXPECTED_EXECUTABLE)
    if not isinstance(lamports, int):
        raise PR115StateEvidenceError(PR115StateEvidenceCode.MALFORMED_ACCOUNT)
    if isinstance(lamports, bool) or lamports < 0:
        raise PR115StateEvidenceError(PR115StateEvidenceCode.MALFORMED_ACCOUNT)
    expected_owner = _expected_owner(policy, address)
    if expected_owner is not None and owner != expected_owner:
        raise PR115StateEvidenceError(PR115StateEvidenceCode.WRONG_OWNER)
    data_base64, data = _decode_account_data(account.get("data"))
    if len(data) > policy.max_account_data_bytes:
        raise PR115StateEvidenceError(PR115StateEvidenceCode.WRONG_DATA_LENGTH)
    data_hash = _hash_bytes(data)
    decoded_hash = _hash_json(
        {
            "address": address,
            "index": index,
            "owner": owner,
            "executable": executable,
            "lamports": lamports,
            "data_hash": data_hash,
            "decoder_version": PR115_DECODER_VERSION,
        }
    )
    return PR115RawAccountSnapshot(
        address=address,
        index=index,
        owner=owner,
        executable=executable,
        lamports=lamports,
        data_base64=data_base64,
        data_hash=data_hash,
        raw_hash=_hash_json(dict(account)),
        decoded_hash=decoded_hash,
    )


def _expected_owner(policy: PR115DecodePolicy, address: str) -> str | None:
    if policy.expected_owner_by_address is None:
        return None
    return policy.expected_owner_by_address.get(address)


def _native_delta(
    pre: PR115RawAccountSnapshot,
    post: PR115RawAccountSnapshot,
) -> PR115NativeLamportDelta:
    if pre.data_base64 or post.data_base64:
        raise PR115StateEvidenceError(PR115StateEvidenceCode.WRONG_DATA_LENGTH)
    return PR115NativeLamportDelta(
        address=post.address,
        pre_lamports=pre.lamports,
        post_lamports=post.lamports,
        delta_lamports=post.lamports - pre.lamports,
        pre_raw_hash=pre.raw_hash,
        post_raw_hash=post.raw_hash,
    )


def _token_delta(
    pre: PR115RawAccountSnapshot,
    post: PR115RawAccountSnapshot,
) -> PR115TokenAccountDelta:
    pre_bytes = _decode_snapshot_data(pre)
    post_bytes = _decode_snapshot_data(post)
    if len(pre_bytes) != SPL_TOKEN_ACCOUNT_LEN:
        raise PR115StateEvidenceError(PR115StateEvidenceCode.WRONG_DATA_LENGTH)
    if len(post_bytes) != SPL_TOKEN_ACCOUNT_LEN:
        raise PR115StateEvidenceError(PR115StateEvidenceCode.WRONG_DATA_LENGTH)

    pre_mint = pre_bytes[SPL_TOKEN_MINT_OFFSET:SPL_TOKEN_OWNER_OFFSET]
    post_mint = post_bytes[SPL_TOKEN_MINT_OFFSET:SPL_TOKEN_OWNER_OFFSET]
    pre_owner = pre_bytes[SPL_TOKEN_OWNER_OFFSET:SPL_TOKEN_AMOUNT_OFFSET]
    post_owner = post_bytes[SPL_TOKEN_OWNER_OFFSET:SPL_TOKEN_AMOUNT_OFFSET]
    if pre_mint != post_mint or pre_owner != post_owner:
        raise PR115StateEvidenceError(PR115StateEvidenceCode.WRONG_OWNER)

    amount_start = SPL_TOKEN_AMOUNT_OFFSET
    amount_end = SPL_TOKEN_AMOUNT_OFFSET + SPL_TOKEN_AMOUNT_LEN
    pre_amount = int.from_bytes(pre_bytes[amount_start:amount_end], "little")
    post_amount = int.from_bytes(post_bytes[amount_start:amount_end], "little")
    from solders.pubkey import Pubkey

    return PR115TokenAccountDelta(
        address=post.address,
        mint_hash=_hash_bytes(post_mint),
        owner_hash=_hash_bytes(post_owner),
        pre_amount=pre_amount,
        post_amount=post_amount,
        delta_amount=post_amount - pre_amount,
        pre_raw_hash=pre.raw_hash,
        post_raw_hash=post.raw_hash,
        mint=str(Pubkey.from_bytes(post_mint)),
        authority=str(Pubkey.from_bytes(post_owner)),
    )


def _decode_snapshot_data(snapshot: PR115RawAccountSnapshot) -> bytes:
    if not snapshot.data_base64:
        return b""
    try:
        return base64.b64decode(snapshot.data_base64, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise PR115StateEvidenceError(PR115StateEvidenceCode.MALFORMED_ACCOUNT) from exc


def _decode_account_data(value: Any) -> tuple[str, bytes]:
    if value in (None, ""):
        return "", b""
    if isinstance(value, (list, tuple)) and len(value) == 2 and value[1] == "base64":
        encoded = value[0]
    elif isinstance(value, str):
        encoded = value
    else:
        raise PR115StateEvidenceError(PR115StateEvidenceCode.MALFORMED_ACCOUNT)
    if not isinstance(encoded, str):
        raise PR115StateEvidenceError(PR115StateEvidenceCode.MALFORMED_ACCOUNT)
    if not encoded:
        return "", b""
    try:
        return encoded, base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise PR115StateEvidenceError(PR115StateEvidenceCode.MALFORMED_ACCOUNT) from exc


def _validate_addresses(addresses: tuple[str, ...]) -> None:
    if not addresses:
        raise PR115StateEvidenceError(PR115StateEvidenceCode.ADDRESS_SET_MISMATCH)
    if len(addresses) != len(set(addresses)):
        raise PR115StateEvidenceError(PR115StateEvidenceCode.DUPLICATE_ADDRESS)
    if any(not address.strip() for address in addresses):
        raise PR115StateEvidenceError(PR115StateEvidenceCode.MALFORMED_ACCOUNT)


def _validate_slots(
    *,
    pre_state_slot: int,
    post_state_slot: int,
    min_context_slot: int,
    pre_root_slot: int | None,
    post_root_slot: int | None,
) -> None:
    values = (pre_state_slot, post_state_slot, min_context_slot)
    if any(not isinstance(value, int) for value in values):
        raise PR115StateEvidenceError(PR115StateEvidenceCode.CONTEXT_SLOT_VIOLATION)
    if any(isinstance(value, bool) for value in values):
        raise PR115StateEvidenceError(PR115StateEvidenceCode.CONTEXT_SLOT_VIOLATION)
    if pre_state_slot < min_context_slot:
        raise PR115StateEvidenceError(PR115StateEvidenceCode.CONTEXT_SLOT_VIOLATION)
    if post_state_slot < min_context_slot:
        raise PR115StateEvidenceError(PR115StateEvidenceCode.CONTEXT_SLOT_VIOLATION)
    if post_state_slot < pre_state_slot:
        raise PR115StateEvidenceError(PR115StateEvidenceCode.CONTEXT_SLOT_VIOLATION)
    _validate_root_slot(pre_root_slot, pre_state_slot)
    _validate_root_slot(post_root_slot, post_state_slot)


def _validate_root_slot(root_slot: int | None, state_slot: int) -> None:
    if root_slot is None:
        return
    if not isinstance(root_slot, int) or isinstance(root_slot, bool):
        raise PR115StateEvidenceError(PR115StateEvidenceCode.CONTEXT_SLOT_VIOLATION)
    if root_slot < state_slot:
        raise PR115StateEvidenceError(PR115StateEvidenceCode.CONTEXT_SLOT_VIOLATION)


def _hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _hash_json(value: Any) -> str:
    try:
        payload = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
            default=lambda item: (
                dict(item) if isinstance(item, Mapping) else _invalid_json(item)
            ),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PR115StateEvidenceError(PR115StateEvidenceCode.MALFORMED_ACCOUNT) from exc
    return hashlib.sha256(payload).hexdigest()


def _invalid_json(value: Any) -> Any:
    raise TypeError("unsupported raw evidence JSON value")


__all__ = [
    "PR115_DECODER_VERSION",
    "PR115_SCHEMA_VERSION",
    "PR115DecodePolicy",
    "PR115MarginfiDecodePolicy",
    "PR115MarginfiRepaymentState",
    "PR115ReadonlyAccountBinding",
    "PR115NativeLamportDelta",
    "PR115RawAccountSnapshot",
    "PR115SimulationOwnedEconomicProof",
    "PR115StateEvidenceCode",
    "PR115StateEvidenceError",
    "PR115TokenAccountDelta",
    "SPL_TOKEN_PROGRAM_ID",
    "SYSTEM_PROGRAM_ID",
    "TOKEN_2022_PROGRAM_ID",
    "build_pr115_proof_from_report",
    "build_pr115_simulation_owned_economic_proof",
]
