from __future__ import annotations
from dataclasses import dataclass
import hashlib, json
from typing import Protocol, Sequence
from solders.pubkey import Pubkey
from .errors import MarginfiRejection, MarginfiRejectionCode
from .pin import MarginfiContractPin

@dataclass(frozen=True, slots=True)
class RpcAccount:
    address: str; owner: str; data: bytes; lamports: int = 0; executable: bool = False

class ReadonlyAccountPort(Protocol):
    def get_multiple_accounts(self, addresses: Sequence[str]) -> tuple[int, tuple[RpcAccount | None, ...]]: ...

@dataclass(frozen=True, slots=True)
class BankSnapshot:
    address: str; group: str; mint: str; token_program: str; liquidity_vault: str; liquidity_vault_authority: str
    oracle_keys: tuple[str, ...]; operational_state: str; available_liquidity: int; outflow_limit: int | None = None

@dataclass(frozen=True, slots=True)
class MarginAccountSnapshot:
    address: str; group: str; authority: str; active_balances: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class MarginfiSnapshot:
    slot: int; group: str; margin_account: MarginAccountSnapshot; bank: BankSnapshot; state_fingerprint: str

def _json_account(account: RpcAccount, expected_disc: bytes, expected_owner: str, label: str) -> dict:
    if account.owner != expected_owner: raise MarginfiRejection(MarginfiRejectionCode.OWNER_MISMATCH, f"{label} owner mismatch")
    if not account.data.startswith(expected_disc): raise MarginfiRejection(MarginfiRejectionCode.DISCRIMINATOR_MISMATCH, f"{label} discriminator mismatch")
    return json.loads(account.data[8:].decode())

class MarginfiAccountReader:
    def __init__(self, pin: MarginfiContractPin, rpc: ReadonlyAccountPort): self.pin, self.rpc = pin, rpc
    def read(self, *, group: str, margin_account: str, authority: str, bank: str, symbol: str, amount: int) -> MarginfiSnapshot:
        slot, accounts = self.rpc.get_multiple_accounts([self.pin.program_id, group, margin_account, bank])
        program, group_acct, ma_acct, bank_acct = accounts
        self.pin.validate_program_account(program)
        if group_acct is None or ma_acct is None or bank_acct is None: raise MarginfiRejection(MarginfiRejectionCode.ACCOUNT_MISSING, "required MarginFi account missing")
        gd = _json_account(group_acct, self.pin.account_discriminator("marginfi_group"), self.pin.program_id, "group")
        md = _json_account(ma_acct, self.pin.account_discriminator("marginfi_account"), self.pin.program_id, "margin account")
        bd = _json_account(bank_acct, self.pin.account_discriminator("bank"), self.pin.program_id, "bank")
        if md.get("group") != group or bd.get("group") != group: raise MarginfiRejection(MarginfiRejectionCode.GROUP_MISMATCH, "margin account/bank group mismatch")
        if md.get("authority") != authority: raise MarginfiRejection(MarginfiRejectionCode.AUTHORITY_MISMATCH, "margin account authority mismatch")
        policy = self.pin.approved_policy(symbol)
        if bd.get("mint") != policy["mint"]: raise MarginfiRejection(MarginfiRejectionCode.UNSUPPORTED_TOKEN, "bank mint is not approved for selected policy")
        if bd.get("token_program") != policy["token_program"]: raise MarginfiRejection(MarginfiRejectionCode.TOKEN_PROGRAM_MISMATCH, "bank token program mismatch")
        if bd.get("operational_state") != "operational": raise MarginfiRejection(MarginfiRejectionCode.BANK_DISABLED, "bank is not operational")
        if int(bd.get("available_liquidity", 0)) < amount: raise MarginfiRejection(MarginfiRejectionCode.INSUFFICIENT_LIQUIDITY, "liquidity vault cannot satisfy borrow")
        active = tuple(md.get("active_balances") or ())
        if bank not in active: active = tuple(sorted((*active, bank), key=lambda k: bytes(Pubkey.from_string(k))))
        bs = BankSnapshot(bank, group, bd["mint"], bd["token_program"], bd["liquidity_vault"], bd["liquidity_vault_authority"], tuple(bd.get("oracle_keys") or ()), bd["operational_state"], int(bd["available_liquidity"]), bd.get("outflow_limit"))
        ms = MarginAccountSnapshot(margin_account, group, authority, active)
        fp = hashlib.sha256(b"".join(a.data for a in (group_acct, ma_acct, bank_acct))).hexdigest()
        return MarginfiSnapshot(slot, group, ms, bs, fp)
