from __future__ import annotations

from src import cli_pr189


def test_run_mode_paper_uses_active_legacy_runtime(monkeypatch) -> None:
    calls: dict[str, list[str]] = {}

    def fake_legacy_main(argv: list[str]) -> int:
        calls["legacy"] = list(argv)
        return 17

    monkeypatch.setattr(cli_pr189.legacy_cli, "main", fake_legacy_main)

    exit_code = cli_pr189.main(["run", "--mode", "paper"])

    assert exit_code == 17
    assert calls == {"legacy": ["run", "--mode", "paper"]}


def test_paper_vertical_preflight_still_rewrites_to_pr189_checks(monkeypatch) -> None:
    calls: dict[str, list[str]] = {}

    def fake_checks_main(argv: list[str]) -> int:
        calls["checks"] = list(argv)
        return 0

    monkeypatch.setattr(cli_pr189.automation_cli_pr189, "main", fake_checks_main)

    exit_code = cli_pr189.main(["paper-vertical-preflight", "--json"])

    assert exit_code == 0
    assert calls == {"checks": ["paper-vertical", "check"]}


def test_readiness_alias_keeps_production_debt_surface(monkeypatch) -> None:
    calls: dict[str, list[str]] = {}

    def fake_checks_main(argv: list[str]) -> int:
        calls["checks"] = list(argv)
        return 0

    monkeypatch.setattr(cli_pr189.automation_cli_pr189, "main", fake_checks_main)

    exit_code = cli_pr189.main(["readiness", "inspect"])

    assert exit_code == 0
    assert calls == {"checks": ["production-debt", "inspect"]}
