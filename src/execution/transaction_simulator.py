"""Account-aware RPC transaction simulator for versioned transaction envelopes."""
from __future__ import annotations
import base64
from .models import AccountSnapshot, CompiledTransaction, RpcClient, SignedTransaction, SimulationReport, TokenDelta

class TransactionSimulator:
    def __init__(self, rpc: RpcClient): self.rpc = rpc

    async def simulate(self, compiled: CompiledTransaction | SignedTransaction, *, final_signed: bool, estimated_network_fee: int = 0) -> SimulationReport:
        if final_signed and not getattr(compiled, "is_fully_signed", False):
            raise ValueError("sigVerify=true requires a fully signed transaction")
        base = compiled.compiled if isinstance(compiled, SignedTransaction) else compiled
        monitored = self._monitored_accounts(base)
        pre = await self._get_multiple_accounts(monitored)
        cfg = {"encoding": "base64", "commitment": "processed", "sigVerify": final_signed, "replaceRecentBlockhash": not final_signed, "innerInstructions": True, "minContextSlot": base.min_context_slot, "accounts": {"encoding": "base64", "addresses": list(monitored)}}
        raw = base64.b64encode(compiled.serialized_transaction).decode()
        resp = await self.rpc.call("simulateTransaction", [raw, cfg])
        value = resp.get("value", resp) if isinstance(resp, dict) else resp
        post = self._decode_simulation_accounts(monitored, value.get("accounts") or [])
        err = value.get("err")
        slot = (resp.get("context") or {}).get("slot", base.blockhash_context.source_slot) if isinstance(resp, dict) else base.blockhash_context.source_slot
        return SimulationReport(err is None, err, tuple(value.get("logs") or ()), value.get("innerInstructions"), value.get("unitsConsumed"), value.get("loadedAccountsDataSize"), value.get("returnData"), pre, post, self._token_deltas(pre, post), sum(p.lamports for p in post) - sum(p.lamports for p in pre), estimated_network_fee, None, int(slot), base.min_context_slot, base.message_hash)

    def _monitored_accounts(self, compiled: CompiledTransaction) -> tuple[str, ...]:
        accounts = [str(compiled.payer)]
        accounts.extend(str(key) for key in compiled.message.account_keys)
        for ix in compiled.instructions:
            accounts.extend(str(meta.pubkey) for meta in ix.accounts)
        return tuple(dict.fromkeys(accounts))

    async def _get_multiple_accounts(self, addresses: tuple[str, ...]) -> tuple[AccountSnapshot, ...]:
        if not addresses: return ()
        resp = await self.rpc.call("getMultipleAccounts", [list(addresses), {"encoding": "base64"}])
        vals = (resp.get("value") if isinstance(resp, dict) else resp) or []
        return tuple(self._account(address, item or {}) for address, item in zip(addresses, vals))

    def _decode_simulation_accounts(self, addresses: tuple[str, ...], accounts: list[object]) -> tuple[AccountSnapshot, ...]:
        return tuple(self._account(address, item or {}) for address, item in zip(addresses, accounts))

    def _account(self, address: str, item: object) -> AccountSnapshot:
        data = item.get("data") or ["", "base64"]
        raw = base64.b64decode(data[0]) if isinstance(data, list) and data and data[0] else b""
        return AccountSnapshot(address, int(item.get("lamports") or 0), item.get("owner") or "", raw, bool(item.get("executable") or False), item.get("rentEpoch"))

    def _token_deltas(self, pre: tuple[AccountSnapshot, ...], post: tuple[AccountSnapshot, ...]) -> tuple[TokenDelta, ...]:
        by_pre = {a.address: a for a in pre}; out = []
        for p in post:
            delta = p.lamports - (by_pre[p.address].lamports if p.address in by_pre else 0)
            if delta: out.append(TokenDelta("native", p.address, delta, 9))
        return tuple(out)

async def get_fee_for_message(rpc: RpcClient, serialized_message: bytes, commitment: str = "processed") -> int | None:
    resp = await rpc.call("getFeeForMessage", [base64.b64encode(serialized_message).decode(), {"commitment": commitment}])
    value = resp.get("value") if isinstance(resp, dict) else resp
    return None if value is None else int(value)
