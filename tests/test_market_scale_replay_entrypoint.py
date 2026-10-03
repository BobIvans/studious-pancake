from pathlib import Path
from dataclasses import asdict
import json
import pytest
from src.paper_shadow.market_scale_replay import load_replay_input, execute_replay

FIXTURE = Path(__file__).parent / "fixtures" / "market_scale_replay.json"


def test_offline_pipeline_installed_boundary_and_canonical_result(tmp_path):
    report = execute_replay(
        FIXTURE, authority_path=tmp_path / "authority.db", workers=2
    )
    assert [r["output_atoms"] for r in report["results"]] == [16, 29, 38]
    assert not report["execution_right"]
    assert report["connected_feeds"] == 0
    assert report["qualification"] == "MODEL_REPLAY_ONLY"


def test_input_rejects_live_flags_and_noninteger_sizes(tmp_path):
    payload = json.loads(FIXTURE.read_text())
    path = tmp_path / "input.json"
    for changes in (
        {"live_enabled": True},
        {"amounts": [True]},
        {"qualification": "LIVE"},
    ):
        path.write_text(json.dumps({**payload, **changes}))
        with pytest.raises(ValueError):
            load_replay_input(path)


def test_module_cli_materializes_html_with_all_exact_legs(tmp_path):
    import subprocess, sys

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.paper_shadow.market_scale_replay",
            str(FIXTURE),
            "--authority-db",
            str(tmp_path / "authority.db"),
            "--output",
            str(tmp_path / "report.json"),
            "--html-review",
            str(tmp_path / "review.html"),
            "--workers",
            "2",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    page = (tmp_path / "review.html").read_text()
    assert page.count("<tr>") == 10
    assert "MODEL_REPLAY_ONLY" in page
    assert (
        json.loads((tmp_path / "report.json").read_text())["execution_right"] is False
    )


def test_replay_loader_preserves_all_declared_fee_state(tmp_path):
    payload = json.loads(FIXTURE.read_text())
    payload["pools"][0]["protocol_fee_rate_ppm"] = 120000
    payload["pools"][0]["accrued_fees_a"] = [3, 1, 0]
    path = tmp_path / "fee-frame.json"
    path.write_text(json.dumps(payload))
    _, plans, _, _ = load_replay_input(path)
    assert plans[0].pools[0].protocol_fee_rate_ppm == 120000
    assert plans[0].pools[0].accrued_fees_a == (3, 1, 0)
    payload["pools"][0]["unknown_fee_field"] = 1
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="unknown pool"):
        load_replay_input(path)
