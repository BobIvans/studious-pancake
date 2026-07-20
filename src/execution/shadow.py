"""PR-013 canonical shadow simulation, reconciliation, ledger, and replay.

This module is deliberately sender-free: it accepts already compiled unsigned
transactions and can only call ``simulateTransaction`` through the injected RPC.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import sqlite3
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

from .models import TransactionPlan, compute_message_hash

SPL_TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM_ID = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
_SYNTHETIC_UNSIGNED_PREFIX = bytes.fromhex("756e7369676e65643a")


class ShadowReason(str, Enum):
    PRE_SIMULATION_FEASIBILITY_REJECTED = "PRE_SIMULATION_FEASIBILITY_REJECTED"
    RPC_TRANSPORT_ERROR = "RPC_TRANSPORT_ERROR"
    RPC_RESPONSE_INVALID = "RPC_RESPONSE_INVALID"
    SIMULATION_PROGRAM_ERROR = "SIMULATION_PROGRAM_ERROR"
    SIMULATION_SLOT_STALE = "SIMULATION_SLOT_STALE"
    MESSAGE_HASH_MISMATCH = "MESSAGE_HASH_MISMATCH"
    SIGNATURE_MODE_MISMATCH = "SIGNATURE_MODE_MISMATCH"
    ACCOUNT_KEYS_MISMATCH = "ACCOUNT_KEYS_MISMATCH"
    BALANCE_VECTOR_LENGTH_MISMATCH = "BALANCE_VECTOR_LENGTH_MISMATCH"
    TOKEN_BALANCE_INVALID = "TOKEN_BALANCE_INVALID"
    TOKEN_PROGRAM_MISMATCH = "TOKEN_PROGRAM_MISMATCH"
    OWNER_MISMATCH = "OWNER_MISMATCH"
    INCOMPLETE_MONITORED_ACCOUNTS = "INCOMPLETE_MONITORED_ACCOUNTS"
    REPAYMENT_NOT_PROVEN = "REPAYMENT_NOT_PROVEN"
    FEE_MISMATCH = "FEE_MISMATCH"
    COMPUTE_LIMIT_EXCEEDED = "COMPUTE_LIMIT_EXCEEDED"
    RENT_CLASSIFICATION_UNKNOWN = "RENT_CLASSIFICATION_UNKNOWN"
    SIMULATED_NET_PROFIT_BELOW_THRESHOLD = "SIMULATED_NET_PROFIT_BELOW_THRESHOLD"
    SHADOW_RECONCILED = "SHADOW_RECONCILED"


class PassKind(str, Enum):
    PROFILE = "PROFILE"
    FINAL = "FINAL"


@dataclass(frozen=True)
class MonitoredTokenAccount:
    account: str
    owner: str
    mint: str
    token_program: str


@dataclass(frozen=True)
class CompilerDiagnostics:
    static_account_keys: tuple[str, ...]
    loaded_writable: tuple[str, ...] = ()
    loaded_readonly: tuple[str, ...] = ()


@dataclass(frozen=True)
class SimulationRequest:
    opportunity_id: str
    attempt_id: str
    plan_hash: str
    message_hash: str
    serialized_transaction: bytes
    expected_signer_count: int
    monitored_native_accounts: tuple[str, ...]
    monitored_token_accounts: tuple[MonitoredTokenAccount, ...] = ()
    settlement_asset: str = "So11111111111111111111111111111111111111112"
    compiler_diagnostics: CompilerDiagnostics = field(
        default_factory=lambda: CompilerDiagnostics(())
    )
    pass_kind: PassKind = PassKind.FINAL
    commitment: str = "processed"
    min_context_slot: int = 0
    sig_verify: bool = False
    replace_recent_blockhash: bool = False

    def rpc_payload(self) -> dict[str, Any]:
        if self.sig_verify or self.replace_recent_blockhash:
            raise ValueError(ShadowReason.SIGNATURE_MODE_MISMATCH.value)
        if self.serialized_transaction.startswith(_SYNTHETIC_UNSIGNED_PREFIX):
            raise ValueError(ShadowReason.MESSAGE_HASH_MISMATCH.value)
        if not re.fullmatch(r"[0-9a-f]{64}", self.message_hash):
            raise ValueError(ShadowReason.MESSAGE_HASH_MISMATCH.value)
        cfg: dict[str, Any] = {
            "encoding": "base64",
            "commitment": self.commitment,
            "sigVerify": False,
            "replaceRecentBlockhash": False,
            "innerInstructions": True,
        }
        if self.min_context_slot:
            cfg["minContextSlot"] = self.min_context_slot
        if self.monitored_native_accounts or self.monitored_token_accounts:
            cfg["accounts"] = {
                "encoding": "base64",
                "addresses": list(self.monitored_native_accounts)
                + [token.account for token in self.monitored_token_accounts],
            }
        return {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "simulateTransaction",
            "params": [base64.b64encode(self.serialized_transaction).decode(), cfg],
        }


@dataclass(frozen=True)
class SimulationReport:
    request: SimulationRequest
    endpoint: str
    context_slot: int | None
    api_version: str | None
    err: Any
    logs: tuple[str, ...]
    inner_instructions: Any
    units_consumed: int | None
    fee: int | None
    loaded_addresses: dict[str, tuple[str, ...]]
    pre_balances: tuple[int, ...]
    post_balances: tuple[int, ...]
    pre_token_balances: tuple[dict[str, Any], ...]
    post_token_balances: tuple[dict[str, Any], ...]
    response_hash: str
    reason: ShadowReason | None = None

    @property
    def success(self) -> bool:
        return self.err is None and self.reason is None


class AccountKeyResolver:
    def resolve(
        self,
        diag: CompilerDiagnostics,
        loaded: dict[str, tuple[str, ...]],
        pre: tuple[int, ...],
        post: tuple[int, ...],
    ) -> tuple[str, ...]:
        if (
            tuple(loaded.get("writable", ())) != diag.loaded_writable
            or tuple(loaded.get("readonly", ())) != diag.loaded_readonly
        ):
            raise ValueError(ShadowReason.ACCOUNT_KEYS_MISMATCH.value)
        full = diag.static_account_keys + diag.loaded_writable + diag.loaded_readonly
        if len(pre) != len(full) or len(post) != len(full):
            raise ValueError(ShadowReason.BALANCE_VECTOR_LENGTH_MISMATCH.value)
        return full

    def key_at(self, keys: tuple[str, ...], index: int) -> str:
        if index < 0 or index >= len(keys):
            raise ValueError(ShadowReason.ACCOUNT_KEYS_MISMATCH.value)
        return keys[index]


class TokenBalanceDecoder:
    def decode(
        self,
        entries: tuple[dict[str, Any], ...],
        keys: tuple[str, ...],
    ) -> dict[tuple[str, str, str], int]:
        out: dict[tuple[str, str, str], int] = {}
        for entry in entries:
            idx = entry.get("accountIndex")
            if not isinstance(idx, int) or idx < 0 or idx >= len(keys):
                raise ValueError(ShadowReason.TOKEN_BALANCE_INVALID.value)
            program = entry.get("programId") or entry.get("programIdIndex") or SPL_TOKEN_PROGRAM_ID
            if program not in (SPL_TOKEN_PROGRAM_ID, TOKEN_2022_PROGRAM_ID):
                raise ValueError(ShadowReason.TOKEN_PROGRAM_MISMATCH.value)
            amount = ((entry.get("uiTokenAmount") or {}).get("amount"))
            if not isinstance(amount, str) or not re.fullmatch(r"\d+", amount):
                raise ValueError(ShadowReason.TOKEN_BALANCE_INVALID.value)
            owner = entry.get("owner")
            mint = entry.get("mint")
            if not owner or not mint:
                raise ValueError(ShadowReason.TOKEN_BALANCE_INVALID.value)
            key = (owner, mint, program)
            out[key] = out.get(key, 0) + int(amount)
        return out


@dataclass(frozen=True)
class RepaymentEvidence:
    required: int
    observed: int
    proven: bool
    reason: str = ""


@dataclass(frozen=True)
class ReconciliationResult:
    reason: ShadowReason
    complete: bool
    native_delta: int
    token_deltas: dict[tuple[str, str, str], int]
    settlement_delta: int
    fee: int
    rent_locked: int
    rent_refunded: int
    repayment: RepaymentEvidence
    theoretical_quote_pnl: int
    conservative_quote_pnl: int
    simulated_executable_pnl: int
    reconciliation_hash: str


class ShadowReconciler:
    def __init__(self, min_profit: int = 0):
        self.min_profit = min_profit

    def reconcile(
        self,
        report: SimulationReport,
        required_repayment: int = 0,
        observed_repayment: int | None = None,
        theoretical_quote_pnl: int = 0,
        conservative_quote_pnl: int = 0,
    ) -> ReconciliationResult:
        if report.reason:
            return self._res(
                report.reason,
                False,
                0,
                {},
                0,
                report.fee or 0,
                0,
                0,
                RepaymentEvidence(required_repayment, 0, False, report.reason.value),
                theoretical_quote_pnl,
                conservative_quote_pnl,
            )
        if report.err is not None:
            return self._res(
                ShadowReason.SIMULATION_PROGRAM_ERROR,
                False,
                0,
                {},
                0,
                report.fee or 0,
                0,
                0,
                RepaymentEvidence(required_repayment, 0, False, "program_error"),
                theoretical_quote_pnl,
                conservative_quote_pnl,
            )
        try:
            keys = AccountKeyResolver().resolve(
                report.request.compiler_diagnostics,
                report.loaded_addresses,
                report.pre_balances,
                report.post_balances,
            )
            pre_tokens = TokenBalanceDecoder().decode(report.pre_token_balances, keys)
            post_tokens = TokenBalanceDecoder().decode(report.post_token_balances, keys)
        except ValueError as exc:
            return self._res(
                ShadowReason(exc.args[0]),
                False,
                0,
                {},
                0,
                report.fee or 0,
                0,
                0,
                RepaymentEvidence(required_repayment, 0, False, exc.args[0]),
                theoretical_quote_pnl,
                conservative_quote_pnl,
            )
        native_delta = sum(
            report.post_balances[i] - report.pre_balances[i]
            for i, key in enumerate(keys)
            if key in report.request.monitored_native_accounts
        )
        token_deltas = {
            key: post_tokens.get(key, 0) - pre_tokens.get(key, 0)
            for key in set(pre_tokens) | set(post_tokens)
        }
        settlement_delta = native_delta
        observed = observed_repayment or 0
        repayment = RepaymentEvidence(
            required_repayment,
            observed,
            observed >= required_repayment,
            "state_observed" if observed_repayment is not None else "state_missing",
        )
        if required_repayment and not repayment.proven:
            reason = ShadowReason.REPAYMENT_NOT_PROVEN
        elif settlement_delta < self.min_profit:
            reason = ShadowReason.SIMULATED_NET_PROFIT_BELOW_THRESHOLD
        else:
            reason = ShadowReason.SHADOW_RECONCILED
        return self._res(
            reason,
            reason == ShadowReason.SHADOW_RECONCILED,
            native_delta,
            token_deltas,
            settlement_delta,
            report.fee or 0,
            0,
            0,
            repayment,
            theoretical_quote_pnl,
            conservative_quote_pnl,
        )

    def _res(
        self,
        reason: ShadowReason,
        complete: bool,
        native_delta: int,
        token_deltas: dict[tuple[str, str, str], int],
        settlement_delta: int,
        fee: int,
        rent_locked: int,
        rent_refunded: int,
        repayment: RepaymentEvidence,
        theoretical_quote_pnl: int,
        conservative_quote_pnl: int,
    ) -> ReconciliationResult:
        payload = {
            "reason": reason.value,
            "native_delta": str(native_delta),
            "token_deltas": {
                str(key): str(value) for key, value in sorted(token_deltas.items())
            },
            "settlement_delta": str(settlement_delta),
            "repayment": repayment.__dict__,
        }
        reconciliation_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return ReconciliationResult(
            reason,
            complete,
            native_delta,
            token_deltas,
            settlement_delta,
            fee,
            rent_locked,
            rent_refunded,
            repayment,
            theoretical_quote_pnl,
            conservative_quote_pnl,
            settlement_delta,
            reconciliation_hash,
        )


class Rpc(Protocol):
    async def call(self, method: str, params: list[Any]) -> Any: ...


class CanonicalSimulator:
    def __init__(self, rpc: Rpc, endpoint: str = "replay://local"):
        self.rpc = rpc
        self.endpoint = sanitize(endpoint)

    async def simulate(self, req: SimulationRequest) -> SimulationReport:
        try:
            payload = req.rpc_payload()
            resp = await self.rpc.call("simulateTransaction", payload["params"])
        except ValueError as exc:
            return _invalid(req, ShadowReason(exc.args[0]))
        except Exception:
            return _invalid(req, ShadowReason.RPC_TRANSPORT_ERROR)
        return parse_simulation_response(req, resp, self.endpoint)


def parse_simulation_response(
    req: SimulationRequest,
    resp: Any,
    endpoint: str = "replay://local",
) -> SimulationReport:
    raw = json.dumps(resp, sort_keys=True, separators=(",", ":"), default=str)
    response_hash = hashlib.sha256(raw.encode()).hexdigest()
    result = resp.get("result", resp) if isinstance(resp, dict) else None
    ctx = (result or {}).get("context") or {}
    value = (result or {}).get("value")
    if not isinstance(value, dict) or "preBalances" not in value or "postBalances" not in value:
        return _invalid(req, ShadowReason.RPC_RESPONSE_INVALID, response_hash)
    slot = ctx.get("slot")
    if req.min_context_slot and (not isinstance(slot, int) or slot < req.min_context_slot):
        reason = ShadowReason.SIMULATION_SLOT_STALE
    else:
        reason = None
    loaded = value.get("loadedAddresses") or {"writable": (), "readonly": ()}
    return SimulationReport(
        req,
        sanitize(endpoint),
        slot,
        ctx.get("apiVersion"),
        value.get("err"),
        tuple(value.get("logs") or ()),
        value.get("innerInstructions"),
        value.get("unitsConsumed"),
        value.get("fee"),
        {
            "writable": tuple(loaded.get("writable") or ()),
            "readonly": tuple(loaded.get("readonly") or ()),
        },
        tuple(int(x) for x in value.get("preBalances") or ()),
        tuple(int(x) for x in value.get("postBalances") or ()),
        tuple(value.get("preTokenBalances") or ()),
        tuple(value.get("postTokenBalances") or ()),
        response_hash,
        reason,
    )


def _invalid(req: SimulationRequest, reason: ShadowReason, h: str = "") -> SimulationReport:
    return SimulationReport(
        req,
        "",
        None,
        None,
        None,
        (),
        None,
        None,
        None,
        {"writable": (), "readonly": ()},
        (),
        (),
        (),
        (),
        h,
        reason,
    )


def sanitize(s: str) -> str:
    return re.sub(
        r"([?&](?:api[-_]?key|key|token|authorization)=)[^&]+",
        r"\1REDACTED",
        s,
        flags=re.I,
    )


def _instruction_identity(planned: Any) -> dict[str, Any]:
    instruction = planned.instruction
    return {
        "program_id": str(instruction.program_id),
        "accounts": [str(getattr(meta, "pubkey", meta)) for meta in instruction.accounts],
        "data": bytes(instruction.data).hex(),
        "role": planned.role,
        "name": planned.name,
    }


def plan_hash(plan: TransactionPlan) -> str:
    payload = {
        "opportunity_id": plan.opportunity_id,
        "payer": str(plan.payer),
        "instructions": [_instruction_identity(ix) for ix in plan.instructions],
        "tip_lamports": plan.tip_policy.lamports,
        "tip_account": str(plan.tip_policy.tip_account) if plan.tip_policy.tip_account else None,
        "compute_unit_limit": plan.compute_budget_policy.unit_limit,
        "compute_unit_price": plan.compute_budget_policy.micro_lamports_per_cu,
        "required_signers": [str(signer) for signer in plan.required_signers],
        "lookup_tables": [str(address) for address in plan.lookup_table_addresses],
        "required_lookup_addresses": [
            str(address) for address in plan.required_lookup_addresses
        ],
        "quote_slot": plan.quote_slot,
        "market_state_slot": plan.market_state_slot,
        "oracle_slot": plan.oracle_slot,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class ShadowPortfolioLedger:
    def __init__(self):
        self.balances: dict[str, int] = {}
        self.applied: set[str] = set()

    def apply(self, outcome_id: str, asset: str, delta: int, gates_ok: bool) -> bool:
        if not gates_ok or outcome_id in self.applied:
            return False
        self.balances[asset] = self.balances.get(asset, 0) + delta
        self.applied.add(outcome_id)
        return True


class ShadowRepository:
    def __init__(self, path: str):
        self.path = path
        self.migrate()

    def migrate(self) -> None:
        with sqlite3.connect(self.path) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS shadow_outcomes (schema_version INTEGER NOT NULL DEFAULT 1, opportunity_id TEXT NOT NULL, attempt_id TEXT NOT NULL, outcome_id TEXT PRIMARY KEY, plan_hash TEXT NOT NULL, message_hash TEXT NOT NULL, request_hash TEXT, response_hash TEXT, reconciliation_hash TEXT, created_at INTEGER NOT NULL, completed_at INTEGER, context_slot INTEGER, terminal_reason TEXT NOT NULL, theoretical_quote_pnl TEXT NOT NULL DEFAULT '0', conservative_quote_pnl TEXT NOT NULL DEFAULT '0', simulated_executable_pnl TEXT NOT NULL DEFAULT '0', simulation_success INTEGER NOT NULL DEFAULT 0, error_code TEXT, units_consumed INTEGER, fee_lamports TEXT, native_deltas_json TEXT NOT NULL DEFAULT '{}', token_deltas_json TEXT NOT NULL DEFAULT '{}', required_repayment TEXT NOT NULL DEFAULT '0', observed_repayment TEXT NOT NULL DEFAULT '0', repayment_proven INTEGER NOT NULL DEFAULT 0, rent_locked TEXT NOT NULL DEFAULT '0', rent_refunded TEXT NOT NULL DEFAULT '0', pr010_decision_json TEXT NOT NULL DEFAULT '{}', executed INTEGER NOT NULL DEFAULT 0, submitted INTEGER NOT NULL DEFAULT 0, signature TEXT DEFAULT NULL, bundle_id TEXT DEFAULT NULL, provenance_json TEXT NOT NULL DEFAULT '{}')"
            )
            db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_shadow_attempt ON shadow_outcomes(opportunity_id, plan_hash, message_hash, attempt_id)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS shadow_ledger_entries (entry_id TEXT PRIMARY KEY, outcome_id TEXT NOT NULL UNIQUE, asset TEXT NOT NULL, delta_base_units TEXT NOT NULL, before_base_units TEXT NOT NULL, after_base_units TEXT NOT NULL, created_at INTEGER NOT NULL)"
            )

    def save(self, req: SimulationRequest, recon: ReconciliationResult) -> str:
        outcome_id = hashlib.sha256(
            (req.attempt_id + req.message_hash + recon.reconciliation_hash).encode()
        ).hexdigest()
        with sqlite3.connect(self.path) as db:
            db.execute(
                "INSERT OR IGNORE INTO shadow_outcomes(opportunity_id,attempt_id,outcome_id,plan_hash,message_hash,response_hash,reconciliation_hash,created_at,completed_at,terminal_reason,theoretical_quote_pnl,conservative_quote_pnl,simulated_executable_pnl,simulation_success,fee_lamports,native_deltas_json,token_deltas_json,required_repayment,observed_repayment,repayment_proven,rent_locked,rent_refunded,provenance_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    req.opportunity_id,
                    req.attempt_id,
                    outcome_id,
                    req.plan_hash,
                    req.message_hash,
                    "",
                    recon.reconciliation_hash,
                    int(time.time()),
                    int(time.time()),
                    recon.reason.value,
                    str(recon.theoretical_quote_pnl),
                    str(recon.conservative_quote_pnl),
                    str(recon.simulated_executable_pnl),
                    1 if recon.complete else 0,
                    str(recon.fee),
                    json.dumps({"native": str(recon.native_delta)}, sort_keys=True),
                    json.dumps(
                        {str(key): str(value) for key, value in recon.token_deltas.items()},
                        sort_keys=True,
                    ),
                    str(recon.repayment.required),
                    str(recon.repayment.observed),
                    1 if recon.repayment.proven else 0,
                    str(recon.rent_locked),
                    str(recon.rent_refunded),
                    json.dumps({"submitted": False, "executed": False}, sort_keys=True),
                ),
            )
        return outcome_id


class ShadowExecutionService:
    def __init__(
        self,
        simulator: CanonicalSimulator,
        reconciler: ShadowReconciler,
        repository: ShadowRepository | None = None,
        ledger: ShadowPortfolioLedger | None = None,
    ):
        self.simulator = simulator
        self.reconciler = reconciler
        self.repository = repository
        self.ledger = ledger or ShadowPortfolioLedger()

    async def run_compiled(
        self,
        req: SimulationRequest,
        *,
        required_repayment: int = 0,
    ) -> ReconciliationResult:
        report = await self.simulator.simulate(req)
        recon = self.reconciler.reconcile(report, required_repayment=required_repayment)
        if self.repository:
            outcome_id = self.repository.save(req, recon)
        else:
            outcome_id = req.attempt_id
        self.ledger.apply(
            outcome_id,
            req.settlement_asset,
            recon.settlement_delta,
            recon.complete and recon.repayment.proven,
        )
        return recon


class ReplayRpcClient:
    def __init__(self, fixtures: dict[str, Any]):
        self.fixtures = fixtures
        self.calls = 0

    async def call(self, method: str, params: list[Any]) -> Any:
        self.calls += 1
        key = hashlib.sha256(
            json.dumps(
                {"method": method, "params": params},
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        if key not in self.fixtures:
            raise RuntimeError("replay fixture missing")
        return self.fixtures[key]
