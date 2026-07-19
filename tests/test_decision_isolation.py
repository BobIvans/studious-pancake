import ast, pathlib


def test_decision_package_forbidden_import_guard():
    forbidden = ("jito", "sender", "rpc", "keypair", "live_gate", "journal", "config")
    for p in pathlib.Path("src/decision").glob("*.py"):
        tree = ast.parse(p.read_text())
        for n in ast.walk(tree):
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in getattr(n, "names", [])] + (
                    [n.module] if getattr(n, "module", None) else []
                )
                assert not any(
                    f in (name or "").lower() for f in forbidden for name in names
                ), (p, names)


def test_no_forbidden_calls_in_decision_package():
    text = "\n".join(p.read_text() for p in pathlib.Path("src/decision").glob("*.py"))
    for token in [
        "sendTransaction",
        "sendBundle",
        "send_bundle",
        "LiveSubmissionPermit",
        "Keypair",
        "private_key",
        "config_write",
        "pickle.load",
        "joblib.load",
    ]:
        assert token not in text
