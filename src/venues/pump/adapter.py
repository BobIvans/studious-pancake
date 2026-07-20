"""PR-023 QUARANTINE: fixture-only Pump adapter pending protocol conformance."""
from __future__ import annotations
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from fractions import Fraction
from typing import Any, Mapping
from src.config.chain_registry import (
    ASSOCIATED_TOKEN_PROGRAM_ADDRESS, SYSTEM_PROGRAM_ADDRESS,
    TOKEN_2022_PROGRAM_ADDRESS, TOKEN_PROGRAM_ADDRESS,
)
from src.execution.models import Instruction
from .models import (
    FeeBreakdown,
    PumpFamily,
    PumpLifecycle,
    PumpQuote,
    PumpSnapshot,
    RawAccount,
    ReasonCode,
    SwapDirection,
)

TOKEN_PROGRAM = TOKEN_PROGRAM_ADDRESS
TOKEN_2022_PROGRAM = TOKEN_2022_PROGRAM_ADDRESS
SYSTEM_PROGRAM = SYSTEM_PROGRAM_ADDRESS
ASSOCIATED_TOKEN_PROGRAM = ASSOCIATED_TOKEN_PROGRAM_ADDRESS


@dataclass(frozen=True)
class ContractSpec:
    family: PumpFamily
    status: str
    contract_version: str
    idl_sha256: str
    program_id: str
    discriminator: bytes
    account_size: int
    ordered_metas: Mapping[str, tuple[str, ...]]


class PumpContractManifest:
    def __init__(self, raw: Mapping[str, Any]):
        self.raw = dict(raw)
        self.live_capability = raw.get("live_capability")
        self.specs = tuple(self._parse(f) for f in raw.get("families", ()))

    @classmethod
    def load(cls, path: str | Path | None = None) -> "PumpContractManifest":
        p = Path(path) if path else Path(__file__).with_name("manifest.json")
        return cls(json.loads(p.read_text()))

    def _parse(self, f: Mapping[str, Any]) -> ContractSpec:
        return ContractSpec(PumpFamily(f["family"]), f["status"], f["contract_version"], f["idl_sha256"], f["program_id"], bytes.fromhex(f["discriminator_hex"]), int(f["account_size"]), {k: tuple(v["ordered_metas"]) for k, v in f.get("instructions", {}).items()})

    def by_family(self, family: PumpFamily) -> ContractSpec | None:
        return next((s for s in self.specs if s.family == family), None)


@dataclass(frozen=True)
class DecodedBondingCurve:
    virtual_base_reserves: int
    virtual_quote_reserves: int
    real_base_reserves: int
    real_quote_reserves: int
    token_total_supply: int
    complete: bool
    base_mint: str
    quote_mint: str


@dataclass(frozen=True)
class DecodedPool:
    base_reserves: int
    quote_vault_amount: int
    virtual_quote_reserves: int
    base_mint: str
    quote_mint: str
    @property
    def effective_quote_reserves(self) -> int: return self.quote_vault_amount + self.virtual_quote_reserves


class PumpAdapter:
    capabilities = frozenset({"DISCOVERY", "EXECUTABLE_SHADOW"})
    live_capability = None
    max_staleness_slots = 20

    def __init__(self, manifest: PumpContractManifest | None = None):
        self.manifest = manifest or PumpContractManifest.load()

    def decode_account(self, family: PumpFamily, account: RawAccount) -> DecodedBondingCurve | DecodedPool:
        spec = self.manifest.by_family(family)
        if spec is None or spec.status != "ENABLED_SHADOW":
            raise ValueError(ReasonCode.DISABLED_UNVERIFIED_CONTRACT.value)
        if account.owner != spec.program_id or account.executable:
            raise ValueError(ReasonCode.PUMP_OWNER_MISMATCH.value)
        if len(account.data) != spec.account_size:
            raise ValueError(ReasonCode.PUMP_LAYOUT_SIZE_MISMATCH.value)
        if not account.data.startswith(spec.discriminator):
            raise ValueError(ReasonCode.PUMP_DISCRIMINATOR_MISMATCH.value)
        body = memoryview(account.data)[8:]
        def u64(off: int) -> int: return int.from_bytes(body[off:off+8], "little")
        def pk(off: int) -> str: return body[off:off+32].tobytes().hex()
        if family is PumpFamily.BONDING_CURVE:
            return DecodedBondingCurve(u64(0), u64(8), u64(16), u64(24), u64(32), bool(body[40]), pk(41), pk(73))
        return DecodedPool(u64(0), u64(8), u64(16), pk(24), pk(56))

    def build_snapshot(self, family: PumpFamily, mint: str, accounts: tuple[RawAccount, ...], token_programs: Mapping[str, str], commitment: str = "processed", destination_verified: bool = False) -> PumpSnapshot:
        if not accounts:
            raise ValueError(ReasonCode.DISABLED_UNVERIFIED_CONTRACT.value)
        read_slot = max(a.slot for a in accounts)
        if any(a.slot > read_slot or a.slot < read_slot for a in accounts):
            raise ValueError(ReasonCode.PUMP_MIXED_SLOT.value)
        decoded = self.decode_account(family, accounts[0])
        quote_mint = decoded.quote_mint
        lifecycle = PumpLifecycle.PUMPSWAP_ACTIVE if family is PumpFamily.PUMPSWAP else (PumpLifecycle.MIGRATION_CONFIRMED if getattr(
            decoded, "complete", False) and destination_verified else PumpLifecycle.BONDING_COMPLETE_PENDING_DESTINATION if getattr(decoded, "complete", False) else PumpLifecycle.BONDING_ACTIVE)
        h = hashlib.sha256(b"".join(a.address.encode()+a.owner.encode()+a.data+a.slot.to_bytes(8, "little") for a in accounts)).hexdigest()
        spec = self.manifest.by_family(family)
        return PumpSnapshot(family, lifecycle, read_slot, commitment, mint, quote_mint, accounts, token_programs, spec.contract_version if spec else "unknown", h)

    def validate_token_policy(self, mint_owner: str, extensions: tuple[str, ...] = (), *, allow_token_2022: bool = False) -> ReasonCode | None:
        if mint_owner == TOKEN_PROGRAM:
            return None
        if mint_owner != TOKEN_2022_PROGRAM:
            return ReasonCode.PUMP_MINT_OWNER_MISMATCH
        allowed = {"metadata_pointer"} if allow_token_2022 else set()
        return None if set(extensions) <= allowed else ReasonCode.PUMP_UNSUPPORTED_TOKEN_EXTENSION

    def quote_exact_in(self, snapshot: PumpSnapshot, direction: SwapDirection, amount: int, min_out: int, fee_bps: int = 100) -> PumpQuote:
        if snapshot.lifecycle not in {PumpLifecycle.BONDING_ACTIVE, PumpLifecycle.PUMPSWAP_ACTIVE}:
            return PumpQuote(direction, amount, 0, 0, 0, min_out, FeeBreakdown(), Fraction(0), snapshot.account_set_hash, snapshot.lifecycle, False, ReasonCode.PUMP_LIFECYCLE_NOT_EXECUTABLE)
        d = self.decode_account(snapshot.family, snapshot.accounts[0])
        x = d.real_quote_reserves + d.virtual_quote_reserves if snapshot.family is PumpFamily.BONDING_CURVE else d.effective_quote_reserves
        y = d.real_base_reserves + d.virtual_base_reserves if snapshot.family is PumpFamily.BONDING_CURVE else d.base_reserves
        if x <= 0 or y <= 0:
            return PumpQuote(direction, amount, 0, 0, 0, min_out, FeeBreakdown(), Fraction(0), snapshot.account_set_hash, snapshot.lifecycle, False, ReasonCode.PUMP_FEE_STATE_INCOMPLETE)
        gross = (amount * y) // (x + amount) if direction is SwapDirection.BUY else (amount * x) // (y + amount)
        fee = gross * fee_bps // 10_000
        net = gross - fee
        return PumpQuote(direction, amount, amount, gross, net, min_out, FeeBreakdown(protocol_fee=fee, total_fee=fee), Fraction(amount, x+amount), snapshot.account_set_hash, snapshot.lifecycle, net >= min_out, None if net >= min_out else ReasonCode.PUMP_FEE_STATE_INCOMPLETE)

    def build_swap_ix(self, snapshot: PumpSnapshot, quote: PumpQuote, accounts: Mapping[str, str], user: str) -> tuple[Instruction, PumpQuote]:
        if not quote.executable_in_shadow or quote.snapshot_hash != snapshot.account_set_hash:
            raise ValueError(ReasonCode.PUMP_LIFECYCLE_NOT_EXECUTABLE.value)
        spec = self.manifest.by_family(snapshot.family)
        name = "buy_v2" if snapshot.family is PumpFamily.BONDING_CURVE and quote.direction is SwapDirection.BUY else "sell_v2" if snapshot.family is PumpFamily.BONDING_CURVE else "buy"
        metas = spec.ordered_metas[name]
        ordered = tuple(user if m == "user" else accounts[m] for m in metas)
        if any(not a for a in ordered):
            raise ValueError(ReasonCode.PUMP_MUTATED_INSTRUCTION.value)
        data = hashlib.sha256((spec.contract_version+":"+name).encode()
                              ).digest()[:8] + quote.exact_in_amount.to_bytes(8, "little") + quote.minimum_out.to_bytes(8, "little")
        return Instruction(spec.program_id, ordered, data, name, "pump_shadow_swap"), quote
