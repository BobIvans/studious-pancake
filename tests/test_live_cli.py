from src.execution import live_control


def test_cli_readiness_json_no_secret(capsys, tmp_path):
    rc = live_control.main(
        ["readiness", "--mode", "shadow", "--config", "config/live_risk.yaml", "--json"]
    )
    out = capsys.readouterr().out.lower()
    assert rc in (0, 2)
    assert "schema_version" in out and "private" not in out and "seed" not in out


def test_cli_arm_wrong_hash_fails(capsys):
    assert (
        live_control.main(
            [
                "live",
                "arm",
                "--confirm-config-hash",
                "bad",
                "--expires-in",
                "60",
                "--config",
                "config/live_risk.yaml",
            ]
        )
        == 2
    )
