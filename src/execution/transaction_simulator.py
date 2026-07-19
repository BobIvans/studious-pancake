"""Canonical exact-message RPC transaction simulator with legacy facade."""
from __future__ import annotations
import base64
from .models import RpcClient, CompiledTransaction, SimulationReport as LegacySimulationReport, AccountSnapshot, TokenDelta
from .shadow import CanonicalSimulator, SimulationRequest, CompilerDiagnostics, parse_simulation_response

class TransactionSimulator(CanonicalSimulator):
    async def simulate(self, request, *args, **kwargs):
        if isinstance(request, SimulationRequest):
            return await super().simulate(request)
        compiled: CompiledTransaction = request
        monitored = tuple(dict.fromkeys([compiled.payer, *(a for ix in compiled.instructions for a in ix.accounts)]))
        pre = await self.rpc.call("getMultipleAccounts", [list(monitored), {"encoding":"base64"}])
        pre_vals=(pre.get("value") if isinstance(pre,dict) else pre) or []
        pre_accounts=[]
        for addr,item in zip(monitored, pre_vals):
            item=item or {}; pre_accounts.append(AccountSnapshot(addr,int(item.get("lamports") or 0),item.get("owner") or "",b""))
        cfg={"encoding":"base64","commitment":"processed","sigVerify":bool(kwargs.get("final_signed", False)),"replaceRecentBlockhash":not bool(kwargs.get("final_signed", False)),"innerInstructions":True,"minContextSlot":compiled.min_context_slot,"accounts":{"encoding":"base64","addresses":list(monitored)}}
        resp=await self.rpc.call("simulateTransaction", [base64.b64encode(compiled.serialized_transaction).decode(), cfg])
        value=(resp.get("value", resp) if isinstance(resp,dict) else {}) or {}
        posts=value.get("accounts") or []
        post_accounts=[]
        for addr,item in zip(monitored, posts):
            item=item or {}; post_accounts.append(AccountSnapshot(addr,int(item.get("lamports") or 0),item.get("owner") or "",b""))
        delta=sum(a.lamports for a in post_accounts)-sum(a.lamports for a in pre_accounts)
        slot=(resp.get("context") or {}).get("slot", compiled.blockhash_context.source_slot) if isinstance(resp,dict) else compiled.blockhash_context.source_slot
        return LegacySimulationReport(value.get("err") is None, value.get("err"), tuple(value.get("logs") or ()), value.get("innerInstructions"), value.get("unitsConsumed"), value.get("loadedAccountsDataSize"), value.get("returnData"), tuple(pre_accounts), tuple(post_accounts), tuple(TokenDelta("native", a.address, a.lamports-(pre_accounts[i].lamports if i < len(pre_accounts) else 0), 9) for i,a in enumerate(post_accounts) if a.lamports-(pre_accounts[i].lamports if i < len(pre_accounts) else 0)), delta, int(kwargs.get("estimated_network_fee",0)), None, int(slot), compiled.min_context_slot, compiled.message_hash)

async def simulate_exact(rpc: RpcClient, request: SimulationRequest):
    return await CanonicalSimulator(rpc).simulate(request)

async def get_fee_for_message(rpc: RpcClient, serialized_message: bytes, commitment: str = "processed") -> int | None:
    encoded = base64.b64encode(serialized_message).decode()
    resp = await rpc.call("getFeeForMessage", [encoded, {"commitment": commitment}])
    value = resp.get("value") if isinstance(resp, dict) else resp
    return None if value is None else int(value)

__all__ = ["CanonicalSimulator", "SimulationRequest", "TransactionSimulator", "parse_simulation_response", "simulate_exact", "get_fee_for_message", "CompilerDiagnostics"]
