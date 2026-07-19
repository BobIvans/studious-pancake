from __future__ import annotations
from dataclasses import dataclass
import hashlib, json
from pathlib import Path
from typing import Any
from .errors import MarginfiRejection, MarginfiRejectionCode

@dataclass(frozen=True, slots=True)
class MarginfiContractPin:
    raw: dict[str, Any]
    path: Path
    @property
    def program_id(self) -> str: return str(self.raw["program_id"])
    @property
    def pin_hash(self) -> str:
        return hashlib.sha256(json.dumps(self.raw, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    def ix_discriminator(self, name: str) -> bytes:
        return bytes.fromhex(self.raw["instructions"][name]["discriminator_hex"])
    def account_discriminator(self, name: str) -> bytes:
        return bytes.fromhex(self.raw["account_discriminators"][name])
    def approved_policy(self, symbol: str) -> dict[str, str]:
        try: return self.raw["approved_banks"][symbol.upper()]
        except KeyError as exc: raise MarginfiRejection(MarginfiRejectionCode.UNSUPPORTED_TOKEN, f"unapproved bank policy: {symbol}") from exc
    def validate_program_account(self, account: Any) -> None:
        if account is None: raise MarginfiRejection(MarginfiRejectionCode.ACCOUNT_MISSING, "pinned program account missing")
        if not getattr(account, "executable", False): raise MarginfiRejection(MarginfiRejectionCode.PIN_MISMATCH, "pinned program is not executable")

def load_marginfi_contract_pin(path: str | Path = "docs/contracts/marginfi_mainnet.json") -> MarginfiContractPin:
    p = Path(path)
    raw = json.loads(p.read_text())
    if raw.get("cluster") != "mainnet-beta" or not raw.get("program_id"):
        raise MarginfiRejection(MarginfiRejectionCode.PIN_MISMATCH, "invalid contract pin")
    return MarginfiContractPin(raw=raw, path=p)
