import hashlib, json, pytest
from src.execution.shadow import *


@pytest.mark.asyncio
async def test_replay_deterministic_and_missing_fixture_no_network():
    msg = b"m"
    req = SimulationRequest(
        "o",
        "a",
        "p",
        hashlib.sha256(msg).hexdigest(),
        msg,
        1,
        ("payer",),
        compiler_diagnostics=CompilerDiagnostics(("payer",)),
    )
    resp = {
        "result": {
            "context": {"slot": 1},
            "value": {
                "err": None,
                "logs": ["repay"],
                "innerInstructions": [],
                "unitsConsumed": 1,
                "fee": 1,
                "preBalances": [1],
                "postBalances": [3],
                "preTokenBalances": [],
                "postTokenBalances": [],
                "loadedAddresses": {"writable": [], "readonly": []},
            },
        }
    }
    key = hashlib.sha256(
        json.dumps(
            {"method": "simulateTransaction", "params": req.rpc_payload()["params"]},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    rpc = ReplayRpcClient({key: resp})
    a = await CanonicalSimulator(rpc).simulate(req)
    b = await CanonicalSimulator(ReplayRpcClient({key: resp})).simulate(req)
    assert a.response_hash == b.response_hash
    assert a.post_balances == (3,)


@pytest.mark.asyncio
async def test_malformed_response_invalid():
    msg = b"m"
    req = SimulationRequest("o", "a", "p", hashlib.sha256(msg).hexdigest(), msg, 1, ())
    key = hashlib.sha256(
        json.dumps(
            {"method": "simulateTransaction", "params": req.rpc_payload()["params"]},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    rep = await CanonicalSimulator(
        ReplayRpcClient({key: {"result": {"context": {"slot": 1}, "value": {}}}})
    ).simulate(req)
    assert rep.reason == ShadowReason.RPC_RESPONSE_INVALID
