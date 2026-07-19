from src.execution.live_control import (
    LiveControlStore,
    LatchReason,
    record_actual_outcome,
)


def test_simulation_alone_does_not_change_realized(tmp_path):
    s = LiveControlStore(tmp_path / "live.sqlite")
    assert s.db.execute("select count(*) from live_actual_outcomes").fetchone()[0] == 0


def test_reconciled_divergence_latches(tmp_path):
    s = LiveControlStore(tmp_path / "live.sqlite")
    record_actual_outcome(
        s,
        attempt_id="a",
        config_hash="h",
        asset="SOL",
        actual_delta=-5000,
        simulated_delta=0,
        tolerance=1000,
        provenance={"kind": "reconciled"},
    )
    assert s.active_latch()["reason"] in {
        LatchReason.SIMULATION_LIVE_DIVERGENCE.value,
        LatchReason.PER_TRADE_CAP_BREACH.value,
    }
