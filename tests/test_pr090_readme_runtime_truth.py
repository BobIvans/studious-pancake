from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
CAPABILITIES = ROOT / "config" / "capabilities.json"


def _readme_text() -> str:
    return README.read_text(encoding="utf-8")


def _readme_text_single_line() -> str:
    return " ".join(_readme_text().split())


def test_readme_paper_status_matches_capability_matrix() -> None:
    capabilities = json.loads(CAPABILITIES.read_text(encoding="utf-8"))
    readme = _readme_text()

    assert capabilities["runtime_modes"]["paper"]["available"] is True
    assert "| Paper trading | `available, fail-closed` |" in readme
    assert "paper trading | `disabled`" not in readme.lower()
    assert "`flashloan-bot run --mode paper`" in readme
    assert "`blocked`/`degraded`" in readme


def test_readme_release_gates_are_review_only_not_live_enablement() -> None:
    readme = _readme_text_single_line()

    assert "Post-merge release-gate status" in readme
    assert "PR-078, PR-079, PR-080 и PR-081" in readme
    assert "не включают live trading" in readme
    assert "не отправляют RPC/Jito transactions" in readme
    assert "ready-for-manual-canary-review" in readme
    assert "не стал автоматическим live bot" in readme


def test_readme_keeps_not_production_ready_and_live_denied_contract() -> None:
    readme = _readme_text()
    readme_lower = readme.lower()

    assert "не является production-ready" in readme
    assert "| Live execution / Jito | `unavailable` |" in readme
    assert "`live` — hard-denied" in readme
    assert "не считайте rpc/jito acknowledgement доказательством" in readme_lower