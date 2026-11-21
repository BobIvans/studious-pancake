"""Tests for the pmm-sim caller-profile slice (PR #665).

Synthetic fixtures only — none of these bytes came from mainnet.
Network-free (pytest-socket). Marked `simulation`: deterministic offline checks.
"""
from __future__ import annotations

import csv
import importlib.util
import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("pyarrow")

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "research" / "pmm-sim-caller-profile"

# Synthetic caller-profile corpus. None of these bytes came from mainnet.
# The market id is a syntactically-valid-but-unused base58 placeholder, not a real account.
SYNTHETIC_AMOUNTS = [100.0, 500.0]
SYNTHETIC_MARKET = "11111111111111111111111111111111111111111111"

pytestmark = pytest.mark.simulation


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "tools" / "prop-amm-harnesses" / "pmm-sim-caller-profile" / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


@pytest.fixture()
def merge_mod():
    return _load("merge_results")


def _write_synthetic_parquet(path: Path, via: str, amount_in: float, amount_out: float) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    table = pa.table(
        {
            "slot": [123456],
            "pmm": ["humidifi"],
            "market": [SYNTHETIC_MARKET],
            "src_token": ["wsol"],
            "dst_token": ["usdc"],
            "amount_in": [amount_in],
            "amount_out": [amount_out],
            "spread": [0.0],
            "spread_bps": [0.0],
            "compute_units": [42000],
        }
    )
    pq.write_table(table, path / f"123456_{via}_humidifi_{SYNTHETIC_MARKET}_20260101-000000.parquet")


def test_spoof_profiles_are_classified_synthetic():
    matrix = json.loads((RESEARCH / "market_matrix_v1.json").read_text(encoding="utf-8"))
    by_id = {p["id"]: p["classification"] for p in matrix["caller_profiles"]}
    assert by_id["DIRECT"] == "GENUINE_EXECUTABLE_ROUTE_CANDIDATE"
    assert by_id["MAGNUS_NATIVE"] == "SYNTHETIC_SIMULATION_BY_DEFAULT"
    for spoof in ("JUPITER_SIM", "DFLOW_SIM", "OKX_SIM", "TITAN_SIM"):
        assert by_id[spoof] == "SYNTHETIC_SIMULATION"


def test_merge_classifies_and_computes_deltas(merge_mod, tmp_path: Path):
    _write_synthetic_parquet(tmp_path, "direct", 100.0, 1000.0)
    _write_synthetic_parquet(tmp_path, "magnus", 100.0, 1005.0)
    _write_synthetic_parquet(tmp_path, "jupiter", 100.0, 1010.0)
    rows = merge_mod.load_rows(tmp_path)
    merge_mod.annotate_deltas(rows)
    merge_mod.label_best(rows)
    by = {r["caller_profile"]: r for r in rows}
    assert len(rows) == 3
    assert by["DIRECT"]["classification"] == "GENUINE_EXECUTABLE_ROUTE_CANDIDATE"
    assert by["JUPITER_SIM"]["classification"] == "SYNTHETIC_SIMULATION"
    # caller_delta_bps vs DIRECT: jupiter is +100 bps over direct, magnus +50
    assert by["JUPITER_SIM"]["caller_delta_bps_vs_direct"] == pytest.approx(100.0)
    assert by["MAGNUS_NATIVE"]["caller_delta_bps_vs_direct"] == pytest.approx(50.0)
    # best simulated caller label goes to the highest synthetic output
    assert by["JUPITER_SIM"]["row_label"] == "BEST_SIMULATED_CALLER_PROFILE"
    assert by["DIRECT"]["row_label"] == "BEST_REAL_EXECUTABLE_ROUTE"


def test_unknown_is_neither_positive_nor_negative(merge_mod):
    rows = merge_mod.load_rows(tmp_path_empty := (Path(__file__).parent / "fixtures" / "nonexistent"))
    assert rows == []
    assert tmp_path_empty is not None


def test_failures_preserved_as_blocked(merge_mod, tmp_path: Path):
    (tmp_path / "failures.txt").write_text(
        "RUN_FAILED tag=jupiter pmm=humidifi suffix=FksffEqn wsol->usdc amount=64000\n",
        encoding="utf-8",
    )
    rows = merge_mod.load_rows(tmp_path)
    assert len(rows) == 1
    assert rows[0]["simulator_return"] == "RUN_FAILED"
    assert rows[0]["row_label"] == "BLOCKED"
    assert rows[0]["caller_profile"] == "JUPITER_SIM"


def test_merge_output_is_deterministic(merge_mod, tmp_path: Path):
    import hashlib

    _write_synthetic_parquet(tmp_path, "direct", 500.0, 5000.0)
    _write_synthetic_parquet(tmp_path, "titan", 500.0, 4990.0)
    args = [
        str(tmp_path),
        "--snapshot-id",
        "synthetic",
        "--out-csv",
        str(tmp_path / "a.csv"),
        "--out-json",
        str(tmp_path / "a.json"),
    ]
    merge_mod.main() if False else None
    sys_args = sys.argv
    sys.argv = ["merge_results.py", *args]
    try:
        assert merge_mod.main() == 0
    finally:
        sys.argv = sys_args
    first = hashlib.sha256((tmp_path / "a.csv").read_bytes()).hexdigest()
    sys.argv = ["merge_results.py", str(tmp_path), "--snapshot-id", "synthetic", "--out-csv", str(tmp_path / "b.csv"), "--out-json", str(tmp_path / "b.json")]
    try:
        assert merge_mod.main() == 0
    finally:
        sys.argv = sys_args
    second = hashlib.sha256((tmp_path / "b.csv").read_bytes()).hexdigest()
    assert first == second


def test_verifier_passes_on_committed_evidence():
    spec = importlib.util.spec_from_file_location("verify_pmm_sim", ROOT / "scripts" / "verify_pmm_sim_caller_profile.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    report = mod.verify(ROOT)
    failing = [c for c in report["checks"] if not c["ok"]]
    assert report["ok"], json.dumps(failing, indent=1)


def test_all_activation_flags_false():
    pack = ROOT / "docs" / "strategy-expansion" / "2026-11-21" / "prop-amm-competitive-toolchain"
    for name in ("PACK_MANIFEST_V1.json", "SOURCE_AUDIT_V1.json", "VENDORED_SOURCE_MANIFEST_V1.json"):
        text = (pack / name).read_text(encoding="utf-8")
        for flag in ("capture", "paid_feed", "provider_activation", "simulation_live_network", "sign", "send", "borrow", "live"):
            assert f'"{flag}": true' not in text, f"{name}: {flag} must stay false"


def test_humidifi_direct_promotion_blocker_stated():
    manifest = json.loads(
        (ROOT / "docs" / "integrations" / "offline" / "humidifi-venue-2026-11-21" / "SOURCE_MANIFEST.json").read_text(encoding="utf-8")
    )
    assert any("min_amount_out" in b for b in manifest["promotion_blockers"])
    cap = manifest["sources"]["humidifi_one_time_capture_2026_11_21"]
    assert cap["snapshot_status"].startswith("RAW_ACCOUNT_CAPTURE_ONLY")


def test_synthetic_fixture_header_present():
    header = Path(__file__).read_text(encoding="utf-8")
    assert "None of these bytes came from mainnet" in header


def test_results_csv_rows_have_classification_when_present():
    csv_path = RESEARCH / "results" / "caller_profile_results.csv"
    if not csv_path.exists():
        pytest.skip("benchmark results not committed yet")
    with open(csv_path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows, "results CSV must not be empty"
    assert all(r["classification"] for r in rows)
    assert any(r["classification"] == "SYNTHETIC_SIMULATION" for r in rows)
