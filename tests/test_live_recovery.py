import pytest
from src.execution.live_control import LiveControlStore, outstanding_attempts
from src.execution.journal import SQLiteAttemptJournal
from src.execution.models import ExecutionState


@pytest.mark.asyncio
async def test_restart_reconstructs_outstanding(tmp_path):
    db = tmp_path / "live.sqlite"
    j = SQLiteAttemptJournal(db)
    await j.create_attempt("opp", "plan", 1, state=ExecutionState.SUBMISSION_UNCERTAIN)
    assert outstanding_attempts(SQLiteAttemptJournal(db)) == 1


def test_jito_ambiguous_distinct_signature_bundle_budget_held(tmp_path):
    s = LiveControlStore(tmp_path / "live.sqlite")
    s.latch("AMBIGUOUS_SUBMISSION", {"signature": "sig1", "bundle_id": "bundle1"})
    latch = s.active_latch()
    assert "sig1" in latch["evidence"] and "bundle1" in latch["evidence"]
