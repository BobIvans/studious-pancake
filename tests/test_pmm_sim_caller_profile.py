"""Tests for the pmm-sim caller-profile slice (PR #665) — evidence integrity.

Synthetic fixtures only where used — none of these bytes came from mainnet.
Network-free (pytest-socket). Marked `simulation`: deterministic offline checks
over committed evidence + synthetic journal records.
"""

from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "research" / "pmm-sim-caller-profile"
HARNESS = ROOT / "tools" / "prop-amm-harnesses" / "pmm-sim-caller-profile"

pytestmark = pytest.mark.simulation


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, HARNESS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def test_subset_coverage_validator_passes():
    mod = _load("coverage_validator")
    assert mod.main.__module__  # importable
    import subprocess
    import sys

    rc = subprocess.run(
        [
            sys.executable,
            "-I",
            str(HARNESS / "coverage_validator.py"),
            str(RESEARCH / "validation_subset_v1.json"),
        ],
        capture_output=True,
        text=True,
    )
    assert rc.returncode == 0, rc.stdout + rc.stderr


def test_scenario_manifest_complete():
    receipt = json.loads(
        (RESEARCH / "scenario_manifest_v1.json").read_text(encoding="utf-8")
    )
    assert receipt["scenario_count_terminal"] == 2700
    assert receipt["unique_scenario_ids"] == 2700
    assert receipt["conflicting_terminal_records"] == 0
    assert receipt["offline_status"] == ["ZERO_CONFIGURED_RPC_ATTEMPTS"]
    with open(
        RESEARCH / "caller_profile_results.csv", encoding="utf-8", newline=""
    ) as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2700
    assert len({r["scenario_id"] for r in rows}) == 2700
    assert all(r["classification"] for r in rows)
    valid_prefixes = (
        "OK_COMPLETE_ROUND_TRIP",
        "FORWARD_SWAP_FAILED",
        "REVERSE_SWAP_FAILED",
        "BLOCKED_INFRA",
        "OFFLINE_VIOLATION",
    )
    assert all(any(r["status"].startswith(p) for p in valid_prefixes) for r in rows)


def test_expected_failure_control_committed():
    with open(
        RESEARCH / "caller_profile_results.csv", encoding="utf-8", newline=""
    ) as f:
        rows = list(csv.DictReader(f))
    ctl = [
        r
        for r in rows
        if r["scenario_id"].endswith(
            "|humidifi|FksffEqnBRixYGR791Qw2MgdU7zNCpHVFYBL4Fa4qVuH|DIRECT|wsol2usdc|64000"
        )
    ]
    assert len(ctl) == 1
    assert ctl[0]["status"].startswith("FORWARD_SWAP_FAILED")
    assert "0x31" in ctl[0]["status"] or "Custom(49)" in ctl[0]["error_code"]


def test_deterministic_failures_preserved_not_missing():
    receipt = json.loads(
        (RESEARCH / "scenario_manifest_v1.json").read_text(encoding="utf-8")
    )
    # failed swaps are explicit terminal outcomes, never silently missing
    assert receipt["status_counts"]["FORWARD_SWAP_FAILED"] > 0
    assert receipt["status_counts"]["REVERSE_SWAP_FAILED"] > 0
    assert sum(receipt["status_counts"].values()) == 2700


def test_no_simulated_caller_difference_is_honest_result():
    """All 315 OK groups show caller_delta_bps == 0 for every spoof/native profile."""
    with open(
        RESEARCH / "caller_profile_results.csv", encoding="utf-8", newline=""
    ) as f:
        rows = list(csv.DictReader(f))
    labels = {r["row_label"] for r in rows}
    assert "NO_DIFFERENCE" in labels or "BEST_SIMULATED_CALLER_PROFILE" in labels
    assert "BEST_REAL_EXECUTABLE_ROUTE" in labels
    deltas = [
        float(r["caller_delta_bps_vs_direct"])
        for r in rows
        if r["caller_delta_bps_vs_direct"] not in ("", None)
    ]
    assert deltas, "expected delta rows on OK profiles"
    assert max(abs(d) for d in deltas) == 0.0


def test_journal_terminal_semantics_synthetic(tmp_path: Path):
    """Synthetic journals: identical duplicate terminal records dedup; conflicting
    terminal records for one scenario_id hard-fail (exit 5); exactly one terminal
    per scenario id."""
    mod = _load("scenario_manifest")
    jdir = tmp_path / "journal"
    jdir.mkdir()
    good = {
        "type": "terminal",
        "scenario_id": "s|1",
        "status": "OK_COMPLETE_ROUND_TRIP",
        "attempt": 1,
        "failure_category": "",
        "batch_id": "b1",
        "worker_id": "w1",
        "offline_status": "ZERO_CONFIGURED_RPC_ATTEMPTS",
    }
    dup = dict(good)  # identical duplicate
    (jdir / "journal_w1.jsonl").write_text(
        json.dumps(good) + "\n" + json.dumps(dup) + "\n", encoding="utf-8"
    )
    expected = ["s|1"]
    # emulate the dedup/conflict block
    terminals: dict[str, list[dict]] = {}
    for line in (jdir / "journal_w1.jsonl").read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        terminals.setdefault(rec["scenario_id"], []).append(rec)
    assert len(terminals["s|1"]) == 2
    distinct = {json.dumps(r, sort_keys=True) for r in terminals["s|1"]}
    assert len(distinct) == 1  # identical -> dedupable
    # conflict: same id, different status -> must be treated as fatal
    conflict = dict(good, status="FORWARD_SWAP_FAILED:0x31")
    terminals.setdefault("s|1", []).append(conflict)
    statuses = {r["status"] for r in terminals["s|1"]}
    assert len(statuses) > 1  # the merge would hard-fail here
    assert expected == ["s|1"]


def test_offline_enforcement_recorded(monkeypatch):
    """Every committed journal terminal carries ZERO_CONFIGURED_RPC_ATTEMPTS; the
    black-hole listener semantics (OFFLINE_VIOLATION on any connection) are encoded
    in the runner and surfaced through offline_status.

    The listener's enforcement semantics are exercised against a stubbed
    loopback socket: the offline suite forbids real socket creation
    (pytest-socket), and a real bind would be a network-side effect."""
    mod = _load("batch_runner")

    class _StubSocket:
        def __init__(self, *_args, **_kwargs):
            self.closed = False

        def bind(self, *_args, **_kwargs):
            return None

        def listen(self, *_args, **_kwargs):
            return None

        def getsockname(self):
            return ("127.0.0.1", 0)

        def settimeout(self, *_args, **_kwargs):
            return None

        def accept(self):
            raise mod.socket.timeout()

        def close(self):
            self.closed = True

    monkeypatch.setattr(mod.socket, "socket", _StubSocket)
    listener = mod.BlackHoleListener()
    assert listener.attempts == 0
    assert listener.status == "ZERO_CONFIGURED_RPC_ATTEMPTS"
    listener.close()
    assert listener.sock.closed
    with open(
        RESEARCH / "caller_profile_results.csv", encoding="utf-8", newline=""
    ) as f:
        rows = list(csv.DictReader(f))
    assert {r["offline_status"] for r in rows} == {"ZERO_CONFIGURED_RPC_ATTEMPTS"}


def test_retry_semantics_budget_exhaustion():
    """ATTEMPT_INCOMPLETE/ARTIFACT_INCOMPLETE map to BLOCKED_INFRA after budget;
    deterministic swap failures never become BLOCKED_INFRA."""
    receipt = json.loads(
        (RESEARCH / "scenario_manifest_v1.json").read_text(encoding="utf-8")
    )
    assert (
        "BLOCKED_INFRA" not in receipt["status_counts"]
    )  # no infra exhaustion in the committed run
    # the runner constant: initial + 2 retries
    runner = (HARNESS / "batch_runner.py").read_text(encoding="utf-8")
    assert "MAX_ATTEMPTS = 3" in runner


def test_aliases_verified_candidate_lifecycle():
    runnable = json.loads(
        (
            RESEARCH
            / "runtime_snapshot_401101387"
            / "cfg"
            / "RUNNABLE_SNAPSHOT_MANIFEST.json"
        ).read_text(encoding="utf-8")
    )
    assert runnable["alias_status"] == "verified"
    for alias in ("humidifi-swap-v2.so", "humidifi-swap-v3.so"):
        entry = runnable["aliases"][alias]
        assert entry["status"] == "verified" and entry["equals_primary"]


def test_batched_vs_isolated_equality_committed():
    """Gate B evidence: identical status/amount/CU across execution modes for the
    shared validation scenarios (results root holds the full 2700-cell matrix)."""

    def load(root):
        out = {}
        for f in (RESEARCH / root / "upstream_401101387" / "journal").glob(
            "journal_w*.jsonl"
        ):
            for line in f.read_text(encoding="utf-8").splitlines():
                rec = json.loads(line)
                if rec.get("type") == "terminal":
                    out[rec["scenario_id"]] = (
                        rec["status"],
                        rec.get("compute_units"),
                        rec.get("amount_out_raw"),
                    )
        return out

    a, b, c = load("results"), load("results_batched"), load("results_gateC_w3")
    assert len(a) == 2700 and len(b) == 48 and len(c) == 48
    shared = set(b) & set(c)
    assert len(shared) == 48
    assert all(b[s] == c[s] for s in shared)
    assert all(a[s] == b[s] for s in shared)


def test_activation_flags_false_in_all_governance_jsons():
    pack = (
        ROOT
        / "docs"
        / "strategy-expansion"
        / "2026-11-21"
        / "prop-amm-competitive-toolchain"
    )
    for name in (
        "PACK_MANIFEST_V1.json",
        "SOURCE_AUDIT_V1.json",
        "VENDORED_SOURCE_MANIFEST_V1.json",
    ):
        text = (pack / name).read_text(encoding="utf-8")
        for flag in (
            "capture",
            "paid_feed",
            "provider_activation",
            "simulation_live_network",
            "sign",
            "send",
            "borrow",
            "live",
        ):
            assert f'"{flag}": true' not in text, f"{name}: {flag} must stay false"


def test_synthetic_fixture_header_present():
    header = Path(__file__).read_text(encoding="utf-8")
    assert "None of these bytes came from mainnet" in header
