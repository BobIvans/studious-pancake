import pytest
from src.execution.live_control import (
    LatchReason,
    LiveAdmissionService,
    LiveControlStore,
    LiveMode,
    LiveReadinessService,
    canonical_policy_hash,
    load_policy,
)
from src.execution.journal import SQLiteAttemptJournal


def test_latch_sticky_blocks_and_clear_requires_action(tmp_path):
    p = load_policy("config/live_risk.yaml")
    p["live_enabled"] = True
    s = LiveControlStore(tmp_path / "live.sqlite")
    j = SQLiteAttemptJournal(tmp_path / "live.sqlite")
    h = canonical_policy_hash(p)
    s.arm(h, 60)
    s.latch(LatchReason.MANUAL_KILL_SWITCH.value, {"reason": "incident"})
    assert not LiveReadinessService(p, s, j).report(LiveMode.LIMITED_LIVE).passed
    assert s.active_latch() is not None
    s.clear_latch(h)
    assert s.active_latch() is None


def test_stop_race_sender_rechecks_latch(tmp_path):
    p = load_policy("config/live_risk.yaml")
    p["live_enabled"] = True
    s = LiveControlStore(tmp_path / "live.sqlite")
    j = SQLiteAttemptJournal(tmp_path / "live.sqlite")
    h = canonical_policy_hash(p)
    s.arm(h, 60)
    r = LiveReadinessService(p, s, j).report(LiveMode.LIMITED_LIVE)
    adm = LiveAdmissionService(p, s, j)
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
    s.latch(LatchReason.MANUAL_KILL_SWITCH.value, {})
    with pytest.raises(PermissionError):
        adm.consume_for_submit(permit, message_hash="m", config_hash=h)
