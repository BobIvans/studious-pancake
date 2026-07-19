import pytest
from src.execution.live_control import (
    LiveAdmissionService,
    LiveControlStore,
    LiveMode,
    LiveReadinessService,
    PermitBoundSender,
    canonical_policy_hash,
    load_policy,
)
from src.execution.journal import SQLiteAttemptJournal


class Transport:
    def __init__(self):
        self.calls = 0

    async def send(self, payload):
        self.calls += 1
        return {"ok": True}


def ready(tmp_path):
    p = load_policy("config/live_risk.yaml")
    p["live_enabled"] = True
    s = LiveControlStore(tmp_path / "live.sqlite")
    j = SQLiteAttemptJournal(tmp_path / "live.sqlite")
    s.arm(canonical_policy_hash(p), 60)
    return p, s, j, LiveReadinessService(p, s, j).report(LiveMode.LIMITED_LIVE)


@pytest.mark.asyncio
async def test_sender_requires_real_unused_permit(tmp_path):
    p, s, j, r = ready(tmp_path)
    adm = LiveAdmissionService(p, s, j)
    t = Transport()
    sender = PermitBoundSender(adm, t)
    with pytest.raises(PermissionError):
        await sender.submit(None, b"x", message_hash="m")
    permit = adm.issue_permit(
        attempt_id="a",
        attempt_generation=1,
        plan_hash="p",
        message_hash="m",
        wallet=p["wallet"]["public_key"],
        route_provider="jupiter",
        market="SOL/USDC",
        readiness=r,
    )
    assert await sender.submit(permit, b"x", message_hash="m") == {"ok": True}
    with pytest.raises(PermissionError):
        await sender.submit(permit, b"x", message_hash="m")
    assert t.calls == 1


def test_wrong_hash_and_wallet_denied(tmp_path):
    p, s, j, r = ready(tmp_path)
    adm = LiveAdmissionService(p, s, j)
    with pytest.raises(PermissionError):
        adm.issue_permit(
            attempt_id="a",
            attempt_generation=1,
            plan_hash="p",
            message_hash="m",
            wallet="wrong",
            route_provider="jupiter",
            market="SOL/USDC",
            readiness=r,
        )
    bad = type("R", (), {"passed": True, "config_hash": "0" * 64})()
    with pytest.raises(PermissionError):
        adm.issue_permit(
            attempt_id="a",
            attempt_generation=1,
            plan_hash="p",
            message_hash="m",
            wallet=p["wallet"]["public_key"],
            route_provider="jupiter",
            market="SOL/USDC",
            readiness=bad,
        )
