import json
import sqlite3

import pytest

from src.intelligence.cli import main
from src.intelligence.common import load_json
from src.intelligence.context_recovery import (
    backup_index,
    restore_to_copy,
    verify_backup,
)
from src.intelligence.reports import build_report, verify_report, bundle_report
from .test_repo import repository
from .test_research import identity


def test_cli_index_export_history_coverage_benchmark_and_archive(tmp_path, capsys):
    repo = repository(tmp_path)
    root = tmp_path / "state"
    prefix = ["--state-root", str(root)]
    assert main(prefix + ["repo", "scan", "--repo", str(repo)]) == 0
    assert json.loads(capsys.readouterr().out)["tracked_entries"] == 4
    assert main(prefix + ["repo", "benchmark"]) == 0
    assert json.loads(capsys.readouterr().out)["passed"] == 3
    assert (
        main(
            prefix
            + [
                "repo",
                "export",
                "--mode",
                "INTERCONNECTED_FILES",
                "--seed",
                "a.py",
                "--budget-bytes",
                "10",
                "--out",
                str(tmp_path / "pack"),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["proof"]["within_budget"]
    assert main(prefix + ["repo", "coverage"]) == 0
    assert any(
        g["reason"] == "SECRET_METADATA_ONLY"
        for g in json.loads(capsys.readouterr().out)["gaps"]
    )
    assert main(prefix + ["repo", "archive", "--out", str(tmp_path / "repo.zip")]) == 0
    capsys.readouterr()
    assert main(prefix + ["storage", "status"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["raw_bytes_seen"] is None
    assert main(prefix + ["storage", "prune", "--execute"]) == 2
    capsys.readouterr()
    assert main(prefix + ["laya", "score-repo", "--goal", "a.py"]) == 0
    assert all(
        r["status"] == "NOT_OBSERVED"
        for r in json.loads(capsys.readouterr().out)["decisions"]
    )


def test_checksumbound_reports_keep_unknown_and_bundle(tmp_path):
    report = tmp_path / "report"
    manifest = build_report(
        {"experiment": identity(), "data_kind": "OFFLINE_TEST_FIXTURE"}, report
    )
    assert verify_report(report)["files"] == 15
    assert load_json(report / "FUNNEL.json")["status"] == "NOT_OBSERVED"
    assert load_json(report / "STORAGE.json")["value"] is None
    assert bundle_report(report, tmp_path / "report.zip")["archive_bytes"] > 0
    (report / "PROVIDER_UTILITY.json").write_text("{}")
    with pytest.raises(ValueError, match="checksum"):
        verify_report(report)


def test_sqlite_wal_backup_restore_copy_and_corruption(tmp_path):
    source = tmp_path / "index.sqlite"
    with sqlite3.connect(source) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE symbols(name TEXT)")
        db.execute("INSERT INTO symbols VALUES ('owner')")
        db.commit()
        proof = backup_index(source, tmp_path / "backup.sqlite")
    restore_to_copy(
        tmp_path / "backup.sqlite",
        tmp_path / "restored.sqlite",
        expected_sha256=proof["sha256"],
    )
    with sqlite3.connect(tmp_path / "restored.sqlite") as restored:
        assert restored.execute("SELECT name FROM symbols").fetchone() == ("owner",)
    with pytest.raises(ValueError, match="exists"):
        backup_index(source, tmp_path / "backup.sqlite")
    (tmp_path / "backup.sqlite").write_bytes(b"broken")
    with pytest.raises(ValueError, match="checksum"):
        verify_backup(tmp_path / "backup.sqlite", proof["sha256"])


def test_cli_compare_campaigns_preserves_unknown_resource_cost(tmp_path, capsys):
    from src.intelligence.common import save_json

    campaign = {
        "experiment": identity(),
        "episodes": [
            {"episode": {"episode_id": "ep", "label_atoms": 5}, "resource_usage": None}
        ],
    }
    save_json(tmp_path / "a.json", campaign)
    save_json(tmp_path / "b.json", campaign)
    assert (
        main(
            [
                "report",
                "compare",
                "--baseline",
                str(tmp_path / "a.json"),
                "--candidate",
                str(tmp_path / "b.json"),
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "NOT_OBSERVED"
    assert result["resource_cost_unknown_episode_ids"] == ["ep"]
    assert result["comparison"]["paired_episode_count"] == 0
