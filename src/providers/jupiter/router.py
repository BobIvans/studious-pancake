"""Authenticated, quota-aware Jupiter Router /swap/v2/build adapter.

This module is deliberately composable-only: it returns raw instruction bundles
and never imports signing, sender, Jito submission, or strategy modules.
"""
from __future__ import annotations

import asyncio
import base64
import json
import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

import aiohttp

from src.execution.models import COMPUTE_BUDGET_PROGRAM_ID, Instruction, SimulationReport

from .quota import (
    JupiterQuotaError,
    JupiterQuotaManager,
    JupiterQuotaMetrics,
    JupiterQuotaPurpose,
    QuotaReservation,
)

JUPITER_ROUTER_ENDPOINT = "/swap/v2/build"
JUPITER_COMPUTE_UNIT_LIMIT_MAX = 1_400_000
JUPITER_U64_MAX = 2**64 - 1
JUPITER_MAX_INTEGER_DIGITS = 20
JUPITER_MAX_ROUTE_PLAN_SEGMENTS = 8
JUPITER_MAX_INSTRUCTIONS_BY_BUCKET: dict[str, int] = {
    "computeBudgetInstructions": 2,
    "setupInstructions": 16,
    "otherInstructions": 16,
}
JUPITER_MAX_ACCOUNTS_PER_INSTRUCTION = 64
JUPITER_MAX_DECODED_INSTRUCTION_BYTES = 4_096
JUPITER_MAX_ALT_TABLES = 8
JUPITER_MAX_ALT_ADDRESSES_PER_TABLE = 256
JUPITER_MAX_TOTAL_ALT_ADDRESSES = 512
JUPITER_BLOCKHASH_BYTES = 32
SYSTEM_PROGRAM_ID = "11111111111111111111111111111111"


class JupiterRejectionReason(str, Enum):
    MISSING_CREDENTIALS = "JUPITER_MISSING_CREDENTIALS"
    QUOTA_RESERVATION_FAILURE = "JUPITER_QUOTA_RESERVATION_FAILURE"
    RATE_LIMITED_429 = "JUPITER_429"
    TIMEOUT = "JUPITER_TIMEOUT"
    SCHEMA_FAILURE = "JUPITER_SCHEMA_FAILURE"
    MINT_AMOUNT_SWAP_MODE_MISMATCH = "JUPITER_MINT_AMOUNT_SWAP_MODE_MISMATCH"
    STALE_BUILD = "JUPITER_STALE_BUILD"
    UNSAFE_TIP = "JUPITER_UNSAFE_TIP"
    ALT_MISMATCH = "JUPITER_ALT_MISMATCH"
    ACCOUNT_OVERFLOW = "JUPITER_ACCOUNT_OVERFLOW"
    SIMULATION_FAILURE = "JUPITER_SIMULATION_FAILURE"
    EXHAUSTED_FALLBACK = "JUPITER_EXHAUSTED_FALLBACK"


class JupiterRouterError(ValueError):
    def __init__(self, reason: JupiterRejectionReason, message: str):
        super().__init__(f"{reason.value}: {message}")
        self.reason = reason


class TipOwner(str, Enum):
    COMPILER_OR_JITO = "COMPILER_OR_JITO"
    JUPITER_SUBMIT_DISABLED = "JUPITER_SUBMIT_DISABLED"


class JupiterHealth(str, Enum):
    READY = "ready"
    RATE_LIMITED = "rate_limited"
    UNHEALTHY = "unhealthy"
    DISABLED_MISSING_CREDENTIALS = "disabled_missing_credentials"


@dataclass(frozen=True)
class JupiterRouterConfig:
    api_base_url: str = "https://api.jup.ag"
    api_key_secret_ref: str = "JUPITER_API_KEY"
    quota_limit: int = 60
    quota_window_seconds: float = 60.0
    finalization_reserve: int = 4
    account_budget_steps: tuple[int, ...] = (64, 56, 50)
    allow_below_50_accounts: bool = False
    include_dexes: tuple[str, ...] = ()
    exclude_dexes: tuple[str, ...] = ()
    dex_policy_reason: str = ""
    timeout_seconds: float = 5.0
    max_build_age_seconds: float = 2.0
    min_blockhash_valid_blocks: int = 20

    def __repr__(self) -> str:
        return (
            "JupiterRouterConfig(api_base_url=%r, api_key_secret_ref=<redacted>, "
            "quota_limit=%r, quota_window_seconds=%r, finalization_reserve=%r)"
            % (
                self.api_base_url,
                self.quota_limit,
                self.quota_window_seconds,
                self.finalization_reserve,
            )
        )


@dataclass(frozen=True)
class JupiterBuildRequest:
    input_mint: str
    output_mint: str
    amount: int
    taker: str
    payer: str | None = None
    slippage_bps: int = 50
    max_accounts: int = 64
    wrap_and_unwrap_sol: bool = False
    for_jito_bundle: bool = False
    include_dexes: tuple[str, ...] = ()
    exclude_dexes: tuple[str, ...] = ()
    tip_owner: TipOwner = TipOwner.COMPILER_OR_JITO
    trace_id: str = ""

    def to_params(self) -> dict[str, str]:
        if self.amount <= 0:
            raise JupiterRouterError(
                JupiterRejectionReason.SCHEMA_FAILURE,
                "amount must be positive base units",
            )
        if not (1 <= self.max_accounts <= 64):
            raise JupiterRouterError(
                JupiterRejectionReason.ACCOUNT_OVERFLOW,
                "maxAccounts must be 1-64",
            )
        if self.max_accounts < 50:
            raise JupiterRouterError(
                JupiterRejectionReason.ACCOUNT_OVERFLOW,
                "maxAccounts below 50 requires explicit policy outside request",
            )
        params = {
            "inputMint": self.input_mint,
            "outputMint": self.output_mint,
            "amount": str(self.amount),
            "taker": self.taker,
            "slippageBps": str(self.slippage_bps),
            "maxAccounts": str(self.max_accounts),
            "wrapAndUnwrapSol": str(self.wrap_and_unwrap_sol).lower(),
            "forJitoBundle": str(self.for_jito_bundle).lower(),
        }
        if self.payer:
            params["payer"] = self.payer
        if self.include_dexes:
            params["dexes"] = ",".join(self.include_dexes)
        if self.exclude_dexes:
            params["excludeDexes"] = ",".join(self.exclude_dexes)
        return params


@dataclass(frozen=True)
class RawAccountMeta:
    pubkey: str
    is_signer: bool
    is_writable: bool


@dataclass(frozen=True)
class JupiterRawInstruction:
    program_id: str
    accounts: tuple[RawAccountMeta, ...]
    data_b64: str
    name: str = "jupiter_instruction"

    @property
    def data(self) -> bytes:
        try:
            decoded = base64.b64decode(self.data_b64, validate=True)
        except Exception as exc:
            raise JupiterRouterError(
                JupiterRejectionReason.SCHEMA_FAILURE,
                "instruction data is not base64",
            ) from exc
        if len(decoded) > JUPITER_MAX_DECODED_INSTRUCTION_BYTES:
            raise JupiterRouterError(
                JupiterRejectionReason.SCHEMA_FAILURE,
                "instruction data exceeds structural budget",
            )
        return decoded

    def to_execution_instruction(self, *, kind: str = "jupiter") -> Instruction:
        return Instruction(
            self.program_id,
            tuple(account.pubkey for account in self.accounts),
            self.data,
            self.name,
            kind,
        )

    def to_solders_instruction(self):
        from solders.instruction import AccountMeta, Instruction as SoldersInstruction
        from solders.pubkey import Pubkey

        return SoldersInstruction(
            Pubkey.from_string(self.program_id),
            self.data,
            [
                AccountMeta(
                    Pubkey.from_string(account.pubkey),
                    account.is_signer,
                    account.is_writable,
                )
                for account in self.accounts
            ],
        )


@dataclass(frozen=True)
class JupiterInstructionBundle:
    input_mint: str
    output_mint: str
    in_amount: int
    out_amount: int
    other_amount_threshold: int
    swap_mode: str
    slippage_bps: int
    route_plan: tuple[Mapping[str, Any], ...]
    compute_unit_price_instructions: tuple[JupiterRawInstruction, ...]
    setup_instructions: tuple[JupiterRawInstruction, ...]
    swap_instruction: JupiterRawInstruction
    cleanup_instruction: JupiterRawInstruction | None
    other_instructions: tuple[JupiterRawInstruction, ...]
    tip_instruction: JupiterRawInstruction | None
    addresses_by_lookup_table_address: Mapping[str, tuple[str, ...]]
    blockhash_with_metadata: Mapping[str, Any]
    received_at: float = field(default_factory=time.time)

    def execution_buckets(self) -> dict[str, tuple[Instruction, ...]]:
        return {
            "compute": tuple(
                instruction.to_execution_instruction(kind="compute_budget")
                for instruction in self.compute_unit_price_instructions
            ),
            "setup": tuple(
                instruction.to_execution_instruction(kind="setup")
                for instruction in self.setup_instructions
            ),
            "swap": (self.swap_instruction.to_execution_instruction(kind="swap"),),
            "cleanup": tuple(
                ()
                if self.cleanup_instruction is None
                else (self.cleanup_instruction.to_execution_instruction(kind="cleanup"),)
            ),
            "other": tuple(
                instruction.to_execution_instruction(kind="other")
                for instruction in self.other_instructions
            ),
            "tip": tuple(
                ()
                if self.tip_instruction is None
                else (self.tip_instruction.to_execution_instruction(kind="tip"),)
            ),
        }


class JupiterRouterAdapter:
    name = "jupiter_router"

    def __init__(
        self,
        config: JupiterRouterConfig,
        quota: JupiterQuotaManager,
        api_key: str | None,
    ) -> None:
        self.config = config
        self.quota = quota
        self._api_key = api_key or ""
        self._health = (
            JupiterHealth.DISABLED_MISSING_CREDENTIALS
            if not self._api_key.strip()
            else JupiterHealth.READY
        )

    def status(self) -> dict[str, str]:
        return {
            "provider": self.name,
            "health": self._health.value,
            "reason": (
                "safe disabled; missing credentials"
                if self._health == JupiterHealth.DISABLED_MISSING_CREDENTIALS
                else self.quota.metrics.circuit_state
            ),
        }

    async def build(
        self,
        session: aiohttp.ClientSession,
        request: JupiterBuildRequest,
        *,
        purpose: JupiterQuotaPurpose | str = JupiterQuotaPurpose.DISCOVERY,
    ) -> JupiterInstructionBundle:
        if not self._api_key.strip():
            raise JupiterRouterError(
                JupiterRejectionReason.MISSING_CREDENTIALS,
                "Jupiter disabled_missing_credentials",
            )

        try:
            token = await self.quota.reserve(
                purpose,
                request_fingerprint=request.trace_id,
            )
        except JupiterQuotaError as exc:
            raise JupiterRouterError(
                JupiterRejectionReason.QUOTA_RESERVATION_FAILURE,
                exc.reason,
            ) from exc

        issued = False
        try:
            async with session.get(
                self.config.api_base_url.rstrip("/") + JUPITER_ROUTER_ENDPOINT,
                params=request.to_params(),
                headers={"x-api-key": self._api_key},
                timeout=self.config.timeout_seconds,
            ) as resp:
                issued = True
                await self.quota.mark_used(token)
                if resp.status == 429:
                    self.quota.record_429(_retry_after(resp.headers.get("Retry-After")))
                    self._health = JupiterHealth.RATE_LIMITED
                    raise JupiterRouterError(
                        JupiterRejectionReason.RATE_LIMITED_429,
                        "Jupiter returned 429; backoff required",
                    )
                if resp.status >= 400:
                    raise JupiterRouterError(
                        JupiterRejectionReason.SCHEMA_FAILURE,
                        f"Jupiter HTTP status {resp.status}",
                    )
                payload = await resp.text()
                data = strict_json_loads(payload)
            self._health = JupiterHealth.READY
            return parse_build_response(data, request)
        except asyncio.TimeoutError as exc:
            self._health = JupiterHealth.UNHEALTHY
            raise JupiterRouterError(
                JupiterRejectionReason.TIMEOUT,
                "Jupiter build timeout",
            ) from exc
        finally:
            if not issued:
                await self.quota.release_unissued(token)


def _retry_after(value: str | None) -> float | None:
    try:
        return None if value is None else max(0.0, float(value))
    except ValueError:
        return None


def strict_json_loads(payload: str) -> Any:
    """Decode provider JSON without duplicate keys or non-finite constants."""

    def reject_constant(value: str) -> None:
        raise JupiterRouterError(
            JupiterRejectionReason.SCHEMA_FAILURE,
            f"non-finite JSON constant rejected: {value}",
        )

    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        seen: dict[str, Any] = {}
        for key, value in pairs:
            if key in seen:
                raise JupiterRouterError(
                    JupiterRejectionReason.SCHEMA_FAILURE,
                    "duplicate JSON key rejected",
                )
            seen[key] = value
        return seen

    try:
        return json.loads(
            payload,
            parse_constant=reject_constant,
            object_pairs_hook=object_pairs,
        )
    except JupiterRouterError:
        raise
    except json.JSONDecodeError as exc:
        raise JupiterRouterError(
            JupiterRejectionReason.SCHEMA_FAILURE,
            "provider JSON could not be decoded",
        ) from exc


def _int_string(
    data: Mapping[str, Any],
    key: str,
    positive: bool = True,
    max_value: int = JUPITER_U64_MAX,
) -> int:
    value = data.get(key)
    if (
        not isinstance(value, str)
        or not value.isdigit()
        or len(value) > JUPITER_MAX_INTEGER_DIGITS
    ):
        raise JupiterRouterError(
            JupiterRejectionReason.SCHEMA_FAILURE,
            f"{key} must be bounded unsigned integer string",
        )
    parsed = int(value)
    if positive and parsed <= 0:
        raise JupiterRouterError(
            JupiterRejectionReason.SCHEMA_FAILURE,
            f"{key} must be positive",
        )
    if parsed > max_value:
        raise JupiterRouterError(
            JupiterRejectionReason.SCHEMA_FAILURE,
            f"{key} exceeds protocol numeric budget",
        )
    return parsed


def _str(data: Mapping[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise JupiterRouterError(
            JupiterRejectionReason.SCHEMA_FAILURE,
            f"missing {key}",
        )
    return value


def _ix(raw: Mapping[str, Any], name: str) -> JupiterRawInstruction:
    allowed = {"programId", "accounts", "data"}
    unknown = set(raw) - allowed
    if unknown:
        raise JupiterRouterError(
            JupiterRejectionReason.SCHEMA_FAILURE,
            f"{name} contains unknown instruction fields",
        )
    accounts = raw.get("accounts")
    if not isinstance(accounts, list):
        raise JupiterRouterError(
            JupiterRejectionReason.SCHEMA_FAILURE,
            f"{name}.accounts missing",
        )
    if len(accounts) > JUPITER_MAX_ACCOUNTS_PER_INSTRUCTION:
        raise JupiterRouterError(
            JupiterRejectionReason.SCHEMA_FAILURE,
            f"{name}.accounts exceeds structural budget",
        )
    metas: list[RawAccountMeta] = []
    for index, account in enumerate(accounts):
        if not isinstance(account, Mapping):
            raise JupiterRouterError(
                JupiterRejectionReason.SCHEMA_FAILURE,
                f"{name}.accounts[{index}] malformed",
            )
        account_unknown = set(account) - {"pubkey", "isSigner", "isWritable"}
        if account_unknown:
            raise JupiterRouterError(
                JupiterRejectionReason.SCHEMA_FAILURE,
                f"{name}.accounts[{index}] contains unknown fields",
            )
        if not isinstance(account.get("isSigner"), bool) or not isinstance(
            account.get("isWritable"),
            bool,
        ):
            raise JupiterRouterError(
                JupiterRejectionReason.SCHEMA_FAILURE,
                "account meta flags required",
            )
        metas.append(
            RawAccountMeta(
                _str(account, "pubkey"),
                account["isSigner"],
                account["isWritable"],
            )
        )
    program_id = _str(raw, "programId")
    if program_id == str(COMPUTE_BUDGET_PROGRAM_ID):
        program_id = COMPUTE_BUDGET_PROGRAM_ID
    instruction = JupiterRawInstruction(program_id, tuple(metas), _str(raw, "data"), name)
    instruction.data
    return instruction


def _ix_list(data: Mapping[str, Any], key: str) -> tuple[JupiterRawInstruction, ...]:
    value = data.get(key)
    if not isinstance(value, list):
        raise JupiterRouterError(
            JupiterRejectionReason.SCHEMA_FAILURE,
            f"{key} must be list",
        )
    max_items = JUPITER_MAX_INSTRUCTIONS_BY_BUCKET[key]
    if len(value) > max_items:
        raise JupiterRouterError(
            JupiterRejectionReason.SCHEMA_FAILURE,
            f"{key} exceeds structural budget",
        )
    instructions: list[JupiterRawInstruction] = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise JupiterRouterError(
                JupiterRejectionReason.SCHEMA_FAILURE,
                f"{key}[{index}] malformed element",
            )
        instructions.append(_ix(item, key))
    return tuple(instructions)


def _route_plan(data: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    value = data.get("routePlan")
    if not isinstance(value, list):
        raise JupiterRouterError(
            JupiterRejectionReason.SCHEMA_FAILURE,
            "routePlan must be list",
        )
    if len(value) > JUPITER_MAX_ROUTE_PLAN_SEGMENTS:
        raise JupiterRouterError(
            JupiterRejectionReason.SCHEMA_FAILURE,
            "routePlan exceeds structural budget",
        )
    route: list[Mapping[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise JupiterRouterError(
                JupiterRejectionReason.SCHEMA_FAILURE,
                f"routePlan[{index}] malformed element",
            )
        if "percent" in item and not isinstance(item["percent"], int):
            raise JupiterRouterError(
                JupiterRejectionReason.SCHEMA_FAILURE,
                f"routePlan[{index}].percent invalid",
            )
        if "bps" in item and not isinstance(item["bps"], int):
            raise JupiterRouterError(
                JupiterRejectionReason.SCHEMA_FAILURE,
                f"routePlan[{index}].bps invalid",
            )
        route.append(item)
    return tuple(route)


def _alt_map(data: Mapping[str, Any]) -> dict[str, tuple[str, ...]]:
    alt_raw = data.get("addressesByLookupTableAddress")
    if alt_raw is None:
        return {}
    if not isinstance(alt_raw, Mapping):
        raise JupiterRouterError(
            JupiterRejectionReason.SCHEMA_FAILURE,
            "addressesByLookupTableAddress invalid",
        )
    if len(alt_raw) > JUPITER_MAX_ALT_TABLES:
        raise JupiterRouterError(
            JupiterRejectionReason.SCHEMA_FAILURE,
            "ALT table count exceeds structural budget",
        )
    alt_map: dict[str, tuple[str, ...]] = {}
    total_addresses = 0
    for key, value in alt_raw.items():
        if not isinstance(key, str) or not key:
            raise JupiterRouterError(
                JupiterRejectionReason.SCHEMA_FAILURE,
                "ALT address key malformed",
            )
        if not isinstance(value, list):
            raise JupiterRouterError(
                JupiterRejectionReason.SCHEMA_FAILURE,
                f"ALT {key} addresses must be list",
            )
        if len(value) > JUPITER_MAX_ALT_ADDRESSES_PER_TABLE:
            raise JupiterRouterError(
                JupiterRejectionReason.SCHEMA_FAILURE,
                f"ALT {key} exceeds per-table address budget",
            )
        addresses: list[str] = []
        for index, address in enumerate(value):
            if not isinstance(address, str) or not address:
                raise JupiterRouterError(
                    JupiterRejectionReason.SCHEMA_FAILURE,
                    f"ALT {key}[{index}] malformed address",
                )
            addresses.append(address)
        total_addresses += len(addresses)
        alt_map[key] = tuple(addresses)
    if total_addresses > JUPITER_MAX_TOTAL_ALT_ADDRESSES:
        raise JupiterRouterError(
            JupiterRejectionReason.SCHEMA_FAILURE,
            "ALT total address budget exceeded",
        )
    return alt_map


def _blockhash(data: Mapping[str, Any]) -> Mapping[str, Any]:
    blockhash = data.get("blockhashWithMetadata")
    if not isinstance(blockhash, Mapping):
        raise JupiterRouterError(
            JupiterRejectionReason.SCHEMA_FAILURE,
            "blockhashWithMetadata invalid",
        )
    blockhash_bytes = blockhash.get("blockhash")
    if (
        not isinstance(blockhash_bytes, list)
        or len(blockhash_bytes) != JUPITER_BLOCKHASH_BYTES
        or any(
            not isinstance(item, int) or isinstance(item, bool) or not 0 <= item <= 255
            for item in blockhash_bytes
        )
    ):
        raise JupiterRouterError(
            JupiterRejectionReason.SCHEMA_FAILURE,
            "blockhashWithMetadata.blockhash invalid",
        )
    if not isinstance(blockhash.get("lastValidBlockHeight"), int) or isinstance(
        blockhash.get("lastValidBlockHeight"),
        bool,
    ):
        raise JupiterRouterError(
            JupiterRejectionReason.SCHEMA_FAILURE,
            "blockhashWithMetadata.lastValidBlockHeight invalid",
        )
    return blockhash


def parse_build_response(
    data: Mapping[str, Any],
    request: JupiterBuildRequest,
    now: float | None = None,
) -> JupiterInstructionBundle:
    if not isinstance(data, Mapping):
        raise JupiterRouterError(
            JupiterRejectionReason.SCHEMA_FAILURE,
            "response must be object",
        )
    allowed = {
        "inputMint",
        "outputMint",
        "inAmount",
        "outAmount",
        "otherAmountThreshold",
        "swapMode",
        "slippageBps",
        "routePlan",
        "computeBudgetInstructions",
        "setupInstructions",
        "swapInstruction",
        "cleanupInstruction",
        "otherInstructions",
        "tipInstruction",
        "addressesByLookupTableAddress",
        "blockhashWithMetadata",
    }
    unknown = set(data) - allowed
    if unknown:
        raise JupiterRouterError(
            JupiterRejectionReason.SCHEMA_FAILURE,
            f"unknown schema fields: {sorted(unknown)}",
        )
    if (
        _str(data, "inputMint") != request.input_mint
        or _str(data, "outputMint") != request.output_mint
        or _int_string(data, "inAmount") != request.amount
        or _str(data, "swapMode") != "ExactIn"
    ):
        raise JupiterRouterError(
            JupiterRejectionReason.MINT_AMOUNT_SWAP_MODE_MISMATCH,
            "quote fields differ from request",
        )
    if not isinstance(data.get("slippageBps"), int) or isinstance(
        data.get("slippageBps"),
        bool,
    ):
        raise JupiterRouterError(
            JupiterRejectionReason.SCHEMA_FAILURE,
            "slippageBps must be integer",
        )
    if data.get("slippageBps") != request.slippage_bps:
        raise JupiterRouterError(
            JupiterRejectionReason.MINT_AMOUNT_SWAP_MODE_MISMATCH,
            "slippage differs",
        )

    swap_raw = data.get("swapInstruction")
    if not isinstance(swap_raw, Mapping):
        raise JupiterRouterError(
            JupiterRejectionReason.SCHEMA_FAILURE,
            "swapInstruction required",
        )
    cleanup_raw = data.get("cleanupInstruction")
    if cleanup_raw is not None and not isinstance(cleanup_raw, Mapping):
        raise JupiterRouterError(
            JupiterRejectionReason.SCHEMA_FAILURE,
            "cleanupInstruction malformed",
        )
    tip_raw = data.get("tipInstruction")
    if tip_raw is not None and not isinstance(tip_raw, Mapping):
        raise JupiterRouterError(
            JupiterRejectionReason.SCHEMA_FAILURE,
            "tipInstruction malformed",
        )
    if tip_raw is not None and request.tip_owner == TipOwner.COMPILER_OR_JITO:
        raise JupiterRouterError(
            JupiterRejectionReason.UNSAFE_TIP,
            "unexpected Jupiter tipInstruction",
        )

    alt_map = _alt_map(data)
    blockhash = _blockhash(data)
    route_plan = _route_plan(data)

    compute_budget = _ix_list(data, "computeBudgetInstructions")
    if (
        len(compute_budget) != 1
        or str(compute_budget[0].program_id) != str(COMPUTE_BUDGET_PROGRAM_ID)
    ):
        raise JupiterRouterError(
            JupiterRejectionReason.SCHEMA_FAILURE,
            "exactly one compute unit price instruction required",
        )

    return JupiterInstructionBundle(
        _str(data, "inputMint"),
        _str(data, "outputMint"),
        _int_string(data, "inAmount"),
        _int_string(data, "outAmount"),
        _int_string(data, "otherAmountThreshold"),
        _str(data, "swapMode"),
        data["slippageBps"],
        route_plan,
        compute_budget,
        _ix_list(data, "setupInstructions"),
        _ix(swap_raw, "swapInstruction"),
        None if cleanup_raw is None else _ix(cleanup_raw, "cleanupInstruction"),
        _ix_list(data, "otherInstructions"),
        None if tip_raw is None else _ix(tip_raw, "tipInstruction"),
        alt_map,
        blockhash,
        now or time.time(),
    )


def calculate_final_cu_limit(report: SimulationReport) -> int:
    if not report.success or report.units_consumed is None:
        raise JupiterRouterError(
            JupiterRejectionReason.SIMULATION_FAILURE,
            "missing successful simulation CU consumption",
        )
    return min(
        math.ceil(report.units_consumed * 1.2),
        JUPITER_COMPUTE_UNIT_LIMIT_MAX,
    )


__all__ = [
    "COMPUTE_BUDGET_PROGRAM_ID",
    "JUPITER_BLOCKHASH_BYTES",
    "JUPITER_COMPUTE_UNIT_LIMIT_MAX",
    "JUPITER_MAX_ACCOUNTS_PER_INSTRUCTION",
    "JUPITER_MAX_ALT_ADDRESSES_PER_TABLE",
    "JUPITER_MAX_ALT_TABLES",
    "JUPITER_MAX_DECODED_INSTRUCTION_BYTES",
    "JUPITER_MAX_INSTRUCTIONS_BY_BUCKET",
    "JUPITER_MAX_INTEGER_DIGITS",
    "JUPITER_MAX_ROUTE_PLAN_SEGMENTS",
    "JUPITER_MAX_TOTAL_ALT_ADDRESSES",
    "JUPITER_ROUTER_ENDPOINT",
    "JUPITER_U64_MAX",
    "JupiterBuildRequest",
    "JupiterHealth",
    "JupiterInstructionBundle",
    "JupiterQuotaError",
    "JupiterQuotaManager",
    "JupiterQuotaMetrics",
    "JupiterQuotaPurpose",
    "JupiterRawInstruction",
    "JupiterRejectionReason",
    "JupiterRouterAdapter",
    "JupiterRouterConfig",
    "JupiterRouterError",
    "QuotaReservation",
    "RawAccountMeta",
    "SYSTEM_PROGRAM_ID",
    "TipOwner",
    "calculate_final_cu_limit",
    "parse_build_response",
    "strict_json_loads",
]
