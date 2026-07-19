"""Account-aware RPC transaction simulator."""
from __future__ import annotations
import base64
from .models import *

class TransactionSimulator:
    def __init__(self, rpc: RpcClient):
        self.rpc = rpc

    async def simulate(self, compiled: CompiledTransaction, *, final_signed: bool, estimated_network_fee: int = 0) -> SimulationReport:
        pre = await self._get_multiple_accounts(compiled.instructions[0].accounts if False else ())
        monitored = self._monitored_accounts(compiled)
        pre = await self._get_multiple_accounts(monitored)
        cfg = {
            "encoding": "base64",
            "commitment": "processed",
            "sigVerify": final_signed,
            "replaceRecentBlockhash": not final_signed,
            "innerInstructions": True,
            "minContextSlot": compiled.min_context_slot,
            "accounts": {"encoding": "base64", "addresses": list(monitored)},
        }
        raw = base64.b64encode(compiled.serialized_transaction).decode()
        resp = await self.rpc.call("simulateTransaction", [raw, cfg])
        value = resp.get("value", resp) if isinstance(resp, dict) else resp
        # Official simulateTransaction result has no preBalances/postBalances contract.
        post = self._decode_simulation_accounts(monitored, value.get("accounts") or [])
        err = value.get("err")
        slot = (resp.get("context") or {}).get("slot", compiled.blockhash_context.source_slot) if isinstance(resp, dict) else compiled.blockhash_context.source_slot
        return SimulationReport(
            success=err is None,
            error=err,
            logs=tuple(value.get("logs") or ()),
            inner_instructions=value.get("innerInstructions"),
            units_consumed=value.get("unitsConsumed"),
            loaded_accounts_data_size=value.get("loadedAccountsDataSize"),
            return_data=value.get("returnData"),
            pre_account_states=pre,
            post_account_states=post,
            token_deltas=self._token_deltas(pre, post),
            native_delta_before_fee=sum(p.lamports for p in post) - sum(p.lamports for p in pre),
            estimated_network_fee=estimated_network_fee,
            simulated_net_profit=None,
            simulation_slot=int(slot),
            min_context_slot=compiled.min_context_slot,
            transaction_message_hash=compiled.message_hash,
        )

    def _monitored_accounts(self, compiled: CompiledTransaction) -> tuple[str, ...]:
        accounts = [compiled.payer]
        for ix in compiled.instructions:
            accounts.extend(ix.accounts)
        return tuple(dict.fromkeys(accounts))

    async def _get_multiple_accounts(self, addresses: tuple[str, ...]) -> tuple[AccountSnapshot, ...]:
        if not addresses:
            return ()
        resp = await self.rpc.call("getMultipleAccounts", [list(addresses), {"encoding": "base64"}])
        vals = (resp.get("value") if isinstance(resp, dict) else resp) or []
        out = []
        for address, item in zip(addresses, vals):
            item = item or {}
            data = item.get("data") or ["", "base64"]
            raw = base64.b64decode(data[0]) if isinstance(data, list) and data and data[0] else b""
            out.append(AccountSnapshot(address, int(item.get("lamports") or 0), item.get("owner") or "", raw, bool(item.get("executable") or False), item.get("rentEpoch")))
        return tuple(out)

    def _decode_simulation_accounts(self, addresses: tuple[str, ...], accounts: list[object]) -> tuple[AccountSnapshot, ...]:
        out = []
        for address, item in zip(addresses, accounts):
            item = item or {}
            data = item.get("data") or ["", "base64"]
            raw = base64.b64decode(data[0]) if isinstance(data, list) and data and data[0] else b""
            out.append(AccountSnapshot(address, int(item.get("lamports") or 0), item.get("owner") or "", raw, bool(item.get("executable") or False), item.get("rentEpoch")))
        return tuple(out)

    def _token_deltas(self, pre: tuple[AccountSnapshot, ...], post: tuple[AccountSnapshot, ...]) -> tuple[TokenDelta, ...]:
        by_pre = {a.address: a for a in pre}
        deltas = []
        for p in post:
            before = by_pre.get(p.address)
            lamport_delta = p.lamports - (before.lamports if before else 0)
            if lamport_delta:
                deltas.append(TokenDelta("native", p.address, lamport_delta, 9))
        return tuple(deltas)

async def get_fee_for_message(rpc: RpcClient, serialized_message: bytes, commitment: str = "processed") -> int | None:
    encoded = base64.b64encode(serialized_message).decode()
    resp = await rpc.call("getFeeForMessage", [encoded, {"commitment": commitment}])
    value = resp.get("value") if isinstance(resp, dict) else resp
    return None if value is None else int(value)
