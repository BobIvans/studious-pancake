"""Import-boundary regressions shared with the isolated installed-wheel probe."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest

pytestmark = pytest.mark.unit


def test_paper_imports_do_not_attempt_quarantined_or_submission_modules(tmp_path):
    root = Path(__file__).resolve().parents[1]
    code = """
import importlib.abc
import sys
sys.path.insert(0, sys.argv[1])
forbidden = (
    "src.execution.shadow", "src.execution.senders", "src.execution.live_control",
    "src.execution.lifecycle", "src.execution.live_gate", "src.ingest",
    "src.legacy_arb_bot",
)
class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == p or fullname.startswith(p + ".") for p in forbidden):
            raise RuntimeError("FORBIDDEN_IMPORT_ATTEMPT:" + fullname)
sys.meta_path.insert(0, Guard())
import src.runtime.runtime_entrypoint
import src.paper_shadow.mpr2602_runtime
assert not any(name in sys.modules for name in forbidden)
print("SENDER_FREE_IMPORTS_PASSED")
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", code, str(root)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "SENDER_FREE_IMPORTS_PASSED"


def test_explicit_source_compatibility_exports_still_resolve():
    import src.execution as exports
    from src.execution.lifecycle import TransactionLifecycleService
    from src.execution.live_gate import LiveSubmissionGate
    from src.execution.transaction_simulator import TransactionSimulator

    assert exports.TransactionLifecycleService is TransactionLifecycleService
    assert exports.LiveSubmissionGate is LiveSubmissionGate
    assert exports.TransactionSimulator is TransactionSimulator
