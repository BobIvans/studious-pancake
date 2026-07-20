import hashlib, json, pytest
from src.execution.shadow import *


def make_req(slot=5):
    msg = b"message-bytes"
    return SimulationRequest(
        "opp",
        "att",
        "plan",
        hashlib.sha256(msg).hexdigest(),
        msg,
        1,
        ("payer",),
        compiler_diagnostics=CompilerDiagnostics(("payer",)),
        min_context_slot=slot,
    )


def rpc_response(slot=5, err=None):
    return {
        "result": {
            "context": {"slot": slot, "apiVersion": "3.1.8"},
            "value": {
                "err": err,
                "logs": ["repay"],
                "innerInstructions": [],
                "unitsConsumed": 1,
                "fee": 5000,
                "preBalances": [10],
                "postBalances": [20],
                "preTokenBalances": [],
                "postTokenBalances": [],
                "loadedAddresses": {"writable": [], "readonly": []},
            },
        }
    }


@pytest.mark.asyncio
async def test_exact_base64_request_shape_and_ledger():
    r = make_req()
    payload = r.rpc_payload()
    key = hashlib.sha256(
        json.dumps(
            {"method": "simulateTransaction", "params": payload["params"]},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    rpc = ReplayRpcClient({key: rpc_response()})
    svc = ShadowExecutionService(
        CanonicalSimulator(rpc), ShadowReconciler(), ledger=ShadowPortfolioLedger()
    )
    out = await svc.run_compiled(r)
    assert payload["params"][1]["encoding"] == "base64"
    assert payload["params"][1]["sigVerify"] is False
    assert payload["params"][1]["replaceRecentBlockhash"] is False
    assert out.reason == ShadowReason.SHADOW_RECONCILED
    assert svc.ledger.balances[r.settlement_asset] == 10


@pytest.mark.asyncio
async def test_stale_slot_no_ledger():
    r = make_req(slot=10)
    payload = r.rpc_payload()
    key = hashlib.sha256(
        json.dumps(
            {"method": "simulateTransaction", "params": payload["params"]},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    svc = ShadowExecutionService(
        CanonicalSimulator(ReplayRpcClient({key: rpc_response(slot=9)})),
        ShadowReconciler(),
        ledger=ShadowPortfolioLedger(),
    )
    out = await svc.run_compiled(r)
    assert out.reason == ShadowReason.SIMULATION_SLOT_STALE
    assert svc.ledger.balances == {}


def test_message_hash_tamper_detected_before_rpc():
    r = make_req()
    object.__setattr__(r, "message_hash", "bad")
    with pytest.raises(ValueError):
        r.rpc_payload()
