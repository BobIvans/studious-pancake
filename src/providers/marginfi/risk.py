from __future__ import annotations
from solders.pubkey import Pubkey
from .accounts import BankSnapshot, MarginAccountSnapshot
from .errors import MarginfiRejection, MarginfiRejectionCode

class MarginfiRiskAccountResolver:
    def resolve(self, margin_account: MarginAccountSnapshot, banks: dict[str, BankSnapshot]) -> tuple[str, ...]:
        out: list[str] = []
        seen: set[str] = set()
        for bank_key in sorted(margin_account.active_balances, key=lambda k: bytes(Pubkey.from_string(k))):
            bank = banks.get(bank_key)
            if bank is None or not bank.oracle_keys: raise MarginfiRejection(MarginfiRejectionCode.ORACLE_INVALID, "missing bank/oracle risk group")
            group = (bank.address, *bank.oracle_keys)
            for key in group:
                if key in seen: raise MarginfiRejection(MarginfiRejectionCode.DUPLICATE_RISK_ACCOUNT, "duplicate risk account")
                seen.add(key); out.append(key)
        return tuple(out)
