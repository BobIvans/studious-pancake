"""Shadow-only Pump adapter with official provenance gates for PR-048."""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from src.config.chain_registry import (
    ASSOCIATED_TOKEN_PROGRAM_ADDRESS,
    SYSTEM_PROGRAM_ADDRESS,
    TOKEN_2022_PROGRAM_ADDRESS,
    TOKEN_PROGRAM_ADDRESS,
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
from .provenance import PumpOfficialSource, PumpProvenanceError, provenance_from_family

TOKEN_PROGRAM = TOKEN_PROGRAM_ADDRESS
TOKEN_2022_PROGRAM = TOKEN_2022_PROGRAM_ADDRESS
SYSTEM_PROGRAM = SYSTEM_PROGRAM_ADDRESS
ASSOCIATED_TOKEN_PROGRAM = ASSOCIATED_TOKEN_PROGRAM_ADDRESS


@dataclass(frozen=True, slots=True)
class ContractSpec:
    family: PumpFamily
    status: str
    contract_version: str
    idl_git_blob_sha: str
    program_id: str
    discriminator: bytes
    account_size: int
    ordered_metas: Mapping[str, tuple[str, ...]]
    instruction_discriminators: Mapping[str, bytes]
    source: PumpOfficialSource

    def validate_shadow_ready(self) -> None:
        self.source.validate_shadow_ready()


class PumpContractManifest:
    def __init__(self, raw: Mapping[str, Any]):
        self.raw = dict(raw)
        self.live_capability = raw.get("live_capability")
        self.specs = tuple(self._parse(f) for f in raw.get("families", ()))

    @classmethod
    def load(cls, path: str | Path | None = None) -> "PumpContractManifest":
        p = Path(path) if path else Path(__file__).with_name("manifest.json")
        return cls(json.loads(p.read_text(encoding="utf-8")))

    def _parse(self, f: Mapping[str, Any]) -> ContractSpec:
        instructions = f.get("instructions", {})
        ordered_metas: dict[str, tuple[str, ...]] = {}
        instruction_discriminators: dict[str, bytes] = {}
        if isinstance(instructions, Mapping):
            for name, raw_instruction in instructions.items():
                if not isinstance(raw_instruction, Mapping):
                    continue
                ordered_metas[str(name)] = tuple(
                    str(item) for item in raw_instruction.get("ordered_metas", ())
                )
                discriminator_hex = str(raw_instruction.get("discriminator_hex", ""))
                if discriminator_hex:
                    instruction_discriminators[str(name)] = bytes.fromhex(
                        discriminator_hex
                    )
        return ContractSpec(
            family=PumpFamily(f["family"]),
            status=str(f["status"]),
            contract_version=str(f["contract_version"]),
            idl_git_blob_sha=str(f.get("idl_git_blob_sha", "")),
            program_id=str(f["program_id"]),
            discriminator=bytes.fromhex(str(f["discriminator_hex"])),
            account_size=int(f["account_size"]),
            ordered_metas=ordered_metas,
            instruction_discriminators=instruction_discriminators,
            source=provenance_from_family(f),
        )

    def by_family(self, family: PumpFamily) -> ContractSpec | None:
        return next((s for s in self.specs if s.family == family), None)

    def shadow_errors(self) -> tuple[str, ...]:
        errors: list[str] = []
        for spec in self.specs:
            try:
                spec.validate_shadow_ready()
            except PumpProvenanceError as exc:
                errors.append(f"{spec.family.value}: {exc}")
        return tuple(errors)


@dataclass(frozen=True, slots=True)
class DecodedBondingCurve:
    virtual_base_reserves: int
    virtual_quote_reserves: int
    real_base_reserves: int
    real_quote_reserves: int
    token_total_supply: int
    complete: bool
    base_mint: str
    quote_mint: str


@dataclass(frozen=True, slots=True)
class DecodedPool:
    base_reserves: int
    quote_vault_amount: int
    virtual_quote_reserves: int
    base_mint: str
    quote_mint: str

    @property
    def effective_quote_reserves(self) -> int:
        return self.quote_vault_amount + self.virtual_quote_reserves


class PumpAdapter:
    capabilities = frozenset({"DISCOVERY", "EXECUTABLE_SHADOW"})
    live_capability = None
    max_staleness_slots = 20

    def __init__(self, manifest: PumpContractManifest | None = None):
        self.manifest = manifest or PumpContractManifest.load()

    def _shadow_spec(self, family: PumpFamily) -> ContractSpec:
        spec = self.manifest.by_family(family)
        if spec is None:
            raise ValueError(ReasonCode.DISABLED_UNVERIFIED_CONTRACT.value)
        try:
            spec.validate_shadow_ready()
        except PumpProvenanceError as exc:
            raise ValueError(ReasonCode.PUMP_OFFICIAL_PROVENANCE_REQUIRED.value) from exc
        return spec

    def decode_account(
        self, family: PumpFamily, account: RawAccount
    ) -> DecodedBondingCurve | DecodedPool:
        spec = self._shadow_spec(family)
        if account.owner != spec.program_id or account.executable:
            raise ValueError(ReasonCode.PUMP_OWNER_MISMATCH.value)
        if len(account.data) < spec.account_size:
            raise ValueError(ReasonCode.PUMP_LAYOUT_SIZE_MISMATCH.value)
        if not account.data.startswith(spec.discriminator):
            raise ValueError(ReasonCode.PUMP_DISCRIMINATOR_MISMATCH.value)
        body = memoryview(account.data)[8:]

        def u64(off: int) -> int:
            return int.from_bytes(body[off : off + 8], "little")

        def i128_non_negative(off: int) -> int:
            value = int.from_bytes(body[off : off + 16], "little", signed=True)
            return max(0, value)

        def pk(off: int) -> str:
            return body[off : off + 32].tobytes().hex()

        if family is PumpFamily.BONDING_CURVE:
            # Official pump-public-docs BondingCurve layout:
            # virtual_token_reserves, virtual_quote_reserves, real_token_reserves,
            # real_quote_reserves, token_total_supply, complete, creator,
            # is_mayhem_mode, is_cashback_coin, quote_mint.
            return DecodedBondingCurve(
                virtual_base_reserves=u64(0),
                virtual_quote_reserves=u64(8),
                real_base_reserves=u64(16),
                real_quote_reserves=u64(24),
                token_total_supply=u64(32),
                complete=bool(body[40]),
                base_mint="",
                quote_mint=pk(75),
            )
        # PumpSwap pool does not itself contain vault balances.  The shadow
        # adapter can verify mints and virtual quote reserves from the official
        # pool account, but quotes remain non-executable until vault snapshots are
        # supplied by a later detector/reconciliation integration.
        return DecodedPool(
            base_reserves=0,
            quote_vault_amount=0,
            virtual_quote_reserves=i128_non_negative(237),
            base_mint=pk(35),
            quote_mint=pk(67),
        )

    def build_snapshot(
        self,
        family: PumpFamily,
        mint: str,
        accounts: tuple[RawAccount, ...],
        token_programs: Mapping[str, str],
        commitment: str = "processed",
        destination_verified: bool = False,
    ) -> PumpSnapshot:
        if not accounts:
            raise ValueError(ReasonCode.DISABLED_UNVERIFIED_CONTRACT.value)
        read_slot = max(a.slot for a in accounts)
        if any(a.slot != read_slot for a in accounts):
            raise ValueError(ReasonCode.PUMP_MIXED_SLOT.value)
        decoded = self.decode_account(family, accounts[0])
        quote_mint = decoded.quote_mint
        if family is PumpFamily.PUMPSWAP:
            lifecycle = PumpLifecycle.PUMPSWAP_ACTIVE
        elif getattr(decoded, "complete", False) and destination_verified:
            lifecycle = PumpLifecycle.MIGRATION_CONFIRMED
        elif getattr(decoded, "complete", False):
            lifecycle = PumpLifecycle.BONDING_COMPLETE_PENDING_DESTINATION
        else:
            lifecycle = PumpLifecycle.BONDING_ACTIVE
        h = hashlib.sha256(
            b"".join(
                a.address.encode()
                + a.owner.encode()
                + a.data
                + a.slot.to_bytes(8, "little")
                for a in accounts
            )
        ).hexdigest()
        spec = self._shadow_spec(family)
        return PumpSnapshot(
            family,
            lifecycle,
            read_slot,
            commitment,
            mint,
            quote_mint,
            accounts,
            token_programs,
            spec.contract_version,
            h,
        )

    def validate_token_policy(
        self,
        mint_owner: str,
        extensions: tuple[str, ...] = (),
        *,
        allow_token_2022: bool = False,
    ) -> ReasonCode | None:
        if mint_owner == TOKEN_PROGRAM:
            return None
        if mint_owner != TOKEN_2022_PROGRAM:
            return ReasonCode.PUMP_MINT_OWNER_MISMATCH
        allowed = {"metadata_pointer"} if allow_token_2022 else set()
        return (
            None
            if set(extensions) <= allowed
            else ReasonCode.PUMP_UNSUPPORTED_TOKEN_EXTENSION
        )

    def quote_exact_in(
        self,
        snapshot: PumpSnapshot,
        direction: SwapDirection,
        amount: int,
        min_out: int,
        fee_bps: int = 100,
    ) -> PumpQuote:
        if snapshot.lifecycle not in {
            PumpLifecycle.BONDING_ACTIVE,
            PumpLifecycle.PUMPSWAP_ACTIVE,
        }:
            return PumpQuote(
                direction,
                amount,
                0,
                0,
                0,
                min_out,
                FeeBreakdown(),
                Fraction(0),
                snapshot.account_set_hash,
                snapshot.lifecycle,
                False,
                ReasonCode.PUMP_LIFECYCLE_NOT_EXECUTABLE,
            )
        d = self.decode_account(snapshot.family, snapshot.accounts[0])
        x = (
            d.real_quote_reserves + d.virtual_quote_reserves
            if snapshot.family is PumpFamily.BONDING_CURVE
            else d.effective_quote_reserves
        )
        y = (
            d.real_base_reserves + d.virtual_base_reserves
            if snapshot.family is PumpFamily.BONDING_CURVE
            else d.base_reserves
        )
        if x <= 0 or y <= 0:
            return PumpQuote(
                direction,
                amount,
                0,
                0,
                0,
                min_out,
                FeeBreakdown(),
                Fraction(0),
                snapshot.account_set_hash,
                snapshot.lifecycle,
                False,
                ReasonCode.PUMP_FEE_STATE_INCOMPLETE,
            )
        gross = (
            (amount * y) // (x + amount)
            if direction is SwapDirection.BUY
            else (amount * x) // (y + amount)
        )
        fee = gross * fee_bps // 10_000
        net = gross - fee
        return PumpQuote(
            direction,
            amount,
            amount,
            gross,
            net,
            min_out,
            FeeBreakdown(protocol_fee=fee, total_fee=fee),
            Fraction(amount, x + amount),
            snapshot.account_set_hash,
            snapshot.lifecycle,
            net >= min_out,
            None if net >= min_out else ReasonCode.PUMP_FEE_STATE_INCOMPLETE,
        )

    def build_swap_ix(
        self,
        snapshot: PumpSnapshot,
        quote: PumpQuote,
        accounts: Mapping[str, str],
        user: str,
    ) -> tuple[Instruction, PumpQuote]:
        if not quote.executable_in_shadow or quote.snapshot_hash != snapshot.account_set_hash:
            raise ValueError(ReasonCode.PUMP_LIFECYCLE_NOT_EXECUTABLE.value)
        spec = self._shadow_spec(snapshot.family)
        if snapshot.family is PumpFamily.BONDING_CURVE:
            name = "buy" if quote.direction is SwapDirection.BUY else "sell"
        else:
            name = "buy" if quote.direction is SwapDirection.BUY else "sell"
        metas = spec.ordered_metas.get(name)
        discriminator = spec.instruction_discriminators.get(name)
        if not metas or discriminator is None:
            raise ValueError(ReasonCode.DISABLED_UNVERIFIED_CONTRACT.value)
        try:
            ordered = tuple(user if m == "user" else accounts[m] for m in metas)
        except KeyError as exc:
            raise ValueError(ReasonCode.PUMP_MUTATED_INSTRUCTION.value) from exc
        if any(not a for a in ordered):
            raise ValueError(ReasonCode.PUMP_MUTATED_INSTRUCTION.value)
        data = (
            discriminator
            + quote.exact_in_amount.to_bytes(8, "little")
            + quote.minimum_out.to_bytes(8, "little")
        )
        return Instruction(spec.program_id, ordered, data, name, "pump_shadow_swap"), quote
