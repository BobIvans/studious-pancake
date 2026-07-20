"""Read-only, slot-aware MarginFi account snapshots from pinned binary layouts."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import time
from typing import Callable, Protocol, Sequence

from solders.pubkey import Pubkey

from .errors import MarginfiRejection, MarginfiRejectionCode
from .layouts import (
    DecodedBank,
    decode_bank,
    decode_group,
    decode_margin_account,
    decode_token_account,
)
from .pin import MarginfiContractPin


@dataclass(frozen=True, slots=True)
class RpcAccount:
    address: str
    owner: str
    data: bytes
    lamports: int = 0
    executable: bool = False


class ReadonlyAccountPort(Protocol):
    def get_multiple_accounts(
        self,
        addresses: Sequence[str],
        *,
        min_context_slot: int | None = None,
    ) -> tuple[int, tuple[RpcAccount | None, ...]]: ...


@dataclass(frozen=True, slots=True)
class BankSnapshot:
    # The first ten fields preserve the pre-PR-028 constructor order.
    address: str
    group: str
    mint: str
    token_program: str
    liquidity_vault: str
    liquidity_vault_authority: str
    oracle_keys: tuple[str, ...]
    operational_state: str
    available_liquidity: int | None
    outflow_limit: int | None = None
    mint_decimals: int = 0
    borrow_limit: int = 0
    origination_fee_raw_i80f48: int = 0
    flags: int = 0

    @property
    def requires_mint_account(self) -> bool:
        return self.token_program == (
            "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
        )


@dataclass(frozen=True, slots=True)
class MarginAccountSnapshot:
    address: str
    group: str
    authority: str
    active_balances: tuple[str, ...]
    target_bank_was_active: bool = False
    account_flags: int = 0


@dataclass(frozen=True, slots=True)
class MarginfiSnapshot:
    # Preserve the old five-argument constructor and append the full bank set.
    slot: int
    group: str
    margin_account: MarginAccountSnapshot
    bank: BankSnapshot
    state_fingerprint: str
    banks: tuple[BankSnapshot, ...] = ()


class MarginfiAccountReader:
    def __init__(
        self,
        pin: MarginfiContractPin,
        rpc: ReadonlyAccountPort,
        *,
        clock: Callable[[], int] | None = None,
    ):
        self.pin = pin
        self.rpc = rpc
        self.clock = clock or (lambda: int(time.time()))

    def read(
        self,
        *,
        group: str,
        margin_account: str,
        authority: str,
        bank: str,
        symbol: str,
        amount: int,
    ) -> MarginfiSnapshot:
        if amount <= 0:
            raise MarginfiRejection(
                MarginfiRejectionCode.INSUFFICIENT_LIQUIDITY,
                "borrow amount must be a positive integer",
            )
        for label, value in (
            ("group", group),
            ("margin account", margin_account),
            ("authority", authority),
            ("bank", bank),
        ):
            try:
                Pubkey.from_string(value)
            except ValueError as exc:
                raise MarginfiRejection(
                    MarginfiRejectionCode.PIN_MISMATCH,
                    f"{label} is not a valid public key",
                ) from exc

        first_slot, first_accounts = self.rpc.get_multiple_accounts(
            [self.pin.program_id, group, margin_account, bank],
            min_context_slot=None,
        )
        if first_slot <= 0 or len(first_accounts) != 4:
            raise MarginfiRejection(
                MarginfiRejectionCode.SLOT_INCONSISTENT,
                "initial MarginFi snapshot has invalid RPC context",
            )
        program, group_account, margin_account_data, target_bank_data = first_accounts
        self.pin.validate_program_account(program)
        if (
            group_account is None
            or margin_account_data is None
            or target_bank_data is None
        ):
            raise MarginfiRejection(
                MarginfiRejectionCode.ACCOUNT_MISSING,
                "required MarginFi account missing",
            )

        decoded_group = decode_group(
            group_account,
            self.pin,
            now_timestamp=self.clock(),
        )
        if decoded_group.paused:
            raise MarginfiRejection(
                MarginfiRejectionCode.PROTOCOL_PAUSED,
                "MarginFi group is in an active protocol pause",
            )

        decoded_margin = decode_margin_account(margin_account_data, self.pin)
        if decoded_margin.group != group:
            raise MarginfiRejection(
                MarginfiRejectionCode.GROUP_MISMATCH,
                "margin account group mismatch",
            )
        if decoded_margin.authority != authority:
            raise MarginfiRejection(
                MarginfiRejectionCode.AUTHORITY_MISMATCH,
                "margin account authority mismatch",
            )
        unsafe_mask = 0
        for name in (
            "account_disabled",
            "account_in_flashloan",
            "account_in_receivership",
            "account_in_deleverage",
            "account_frozen",
            "account_in_order_execution",
        ):
            unsafe_mask |= int(self.pin.raw["flags"][name])
        if decoded_margin.account_flags & unsafe_mask:
            raise MarginfiRejection(
                MarginfiRejectionCode.ACCOUNT_STATE_INVALID,
                "margin account is disabled, frozen, or already in a protected execution state",
            )

        decoded_target = decode_bank(
            target_bank_data,
            self.pin,
            bank_address=bank,
        )
        if decoded_target.group != group:
            raise MarginfiRejection(
                MarginfiRejectionCode.GROUP_MISMATCH,
                "target bank group mismatch",
            )
        if decoded_target.operational_state != 1:
            raise MarginfiRejection(
                MarginfiRejectionCode.BANK_DISABLED,
                "target bank is not Operational",
            )
        policy = self.pin.approved_policy(symbol)
        if decoded_target.mint != policy["mint"]:
            raise MarginfiRejection(
                MarginfiRejectionCode.UNSUPPORTED_TOKEN,
                "target bank mint is not approved for the selected policy",
            )
        if decoded_target.token_program != policy["token_program"]:
            raise MarginfiRejection(
                MarginfiRejectionCode.TOKEN_PROGRAM_MISMATCH,
                "target bank token program does not match the selected policy",
            )
        if decoded_target.borrow_limit and amount > decoded_target.borrow_limit:
            raise MarginfiRejection(
                MarginfiRejectionCode.INSUFFICIENT_LIQUIDITY,
                "requested amount exceeds the bank's configured borrow limit",
            )

        additional_keys = tuple(
            key for key in decoded_margin.active_balances if key != bank
        )
        second_addresses = [*additional_keys, decoded_target.liquidity_vault]
        second_slot, second_accounts = self.rpc.get_multiple_accounts(
            second_addresses,
            min_context_slot=first_slot,
        )
        if second_slot < first_slot or len(second_accounts) != len(second_addresses):
            raise MarginfiRejection(
                MarginfiRejectionCode.SLOT_INCONSISTENT,
                "follow-up MarginFi snapshot predates or does not match the initial context",
            )

        additional_snapshots: list[BankSnapshot] = []
        for key, account in zip(additional_keys, second_accounts[:-1], strict=True):
            decoded = decode_bank(account, self.pin, bank_address=key)
            if decoded.group != group:
                raise MarginfiRejection(
                    MarginfiRejectionCode.GROUP_MISMATCH,
                    f"active bank {key} belongs to another group",
                )
            additional_snapshots.append(
                self._bank_snapshot(key, decoded, available_liquidity=None)
            )

        vault_account = second_accounts[-1]
        decoded_vault = decode_token_account(
            vault_account,
            token_program=decoded_target.token_program,
            expected_mint=decoded_target.mint,
        )
        if decoded_vault.amount < amount:
            raise MarginfiRejection(
                MarginfiRejectionCode.INSUFFICIENT_LIQUIDITY,
                "liquidity vault cannot satisfy the requested borrow",
            )

        target_snapshot = self._bank_snapshot(
            bank,
            decoded_target,
            available_liquidity=decoded_vault.amount,
        )
        projected = set(decoded_margin.active_balances)
        target_was_active = bank in projected
        projected.add(bank)
        projected_balances = tuple(
            sorted(projected, key=lambda value: bytes(Pubkey.from_string(value)))
        )
        margin_snapshot = MarginAccountSnapshot(
            address=margin_account,
            group=group,
            authority=authority,
            active_balances=projected_balances,
            target_bank_was_active=target_was_active,
            account_flags=decoded_margin.account_flags,
        )
        banks = tuple(
            sorted(
                (*additional_snapshots, target_snapshot),
                key=lambda item: bytes(Pubkey.from_string(item.address)),
            )
        )
        fingerprint_accounts = (
            group_account,
            margin_account_data,
            target_bank_data,
            *second_accounts,
        )
        fingerprint = hashlib.sha256(
            b"".join(
                str(account.address).encode()
                + str(account.owner).encode()
                + bytes(account.data)
                for account in fingerprint_accounts
                if account is not None
            )
        ).hexdigest()
        return MarginfiSnapshot(
            slot=second_slot,
            group=group,
            margin_account=margin_snapshot,
            bank=target_snapshot,
            state_fingerprint=fingerprint,
            banks=banks,
        )

    @staticmethod
    def _bank_snapshot(
        address: str,
        decoded: DecodedBank,
        *,
        available_liquidity: int | None,
    ) -> BankSnapshot:
        return BankSnapshot(
            address=address,
            group=decoded.group,
            mint=decoded.mint,
            token_program=decoded.token_program,
            liquidity_vault=decoded.liquidity_vault,
            liquidity_vault_authority=decoded.liquidity_vault_authority,
            oracle_keys=decoded.oracle_keys,
            operational_state=(
                "operational" if decoded.operational_state == 1 else "non-operational"
            ),
            available_liquidity=available_liquidity,
            mint_decimals=decoded.mint_decimals,
            borrow_limit=decoded.borrow_limit,
            origination_fee_raw_i80f48=decoded.origination_fee_raw_i80f48,
            flags=decoded.flags,
        )
