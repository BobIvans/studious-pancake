"""Run in an isolated installed-wheel interpreter outside any checkout."""

from __future__ import annotations

import contextlib
import importlib.abc
import io
import json
import socket
import sys
from pathlib import Path

forbidden_prefixes = (
    "src.execution.senders",
    "src.execution.sender",
    "src.execution.submission",
    "src.execution.live_control",
    "src.execution.shadow",
    "src.execution.lifecycle",
    "src.execution.live_gate",
    "src.legacy_arb_bot",
    "src.ingest",
)
import_attempts = []
network_attempts = []


class ImportGuard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(
            fullname == p or fullname.startswith(p + ".") for p in forbidden_prefixes
        ):
            import_attempts.append(fullname)
            raise RuntimeError("FORBIDDEN_DEFAULT_IMPORT:" + fullname)
        return None


def reject_dns(*args, **kwargs):
    network_attempts.append("DNS")
    raise RuntimeError("UNEXPECTED_DEFAULT_NETWORK")


original_connect = socket.socket.connect


def guarded_connect(self, address):
    if self.family != socket.AF_UNIX:
        network_attempts.append("CONNECT")
        raise RuntimeError("UNEXPECTED_DEFAULT_NETWORK")
    return original_connect(self, address)


sys.meta_path.insert(0, ImportGuard())
socket.getaddrinfo = reject_dns
socket.socket.connect = guarded_connect
from src.cli_pr189 import main

stream = io.StringIO()
with contextlib.redirect_stdout(stream):
    code = main(["run", "--mode", "paper", "--db-path", "paper.sqlite3", "--json"])
reports = [
    json.loads(line) for line in stream.getvalue().splitlines() if line.startswith("{")
]
if len(reports) != 1:
    raise RuntimeError("EXPECTED_ONE_SERVICE_REPORT:" + stream.getvalue())
report = reports[0]
import src.paper_shadow.mpr2602_runtime as identity

if "site-packages" not in str(Path(identity.__file__).resolve()):
    raise RuntimeError("NOT_AN_INSTALLED_WHEEL")
if code != 5 or report["status"] != "BLOCKED":
    raise RuntimeError("DEFAULT_SERVICE_DID_NOT_FAIL_CLOSED")
if report.get("terminal_reason") != "BLOCKED_EXTERNAL":
    raise RuntimeError("DEFAULT_SERVICE_DID_NOT_REPORT_BLOCKED_EXTERNAL")
for field in ("sender_imported", "submission_allowed", "live_enabled"):
    if report.get(field) is not False:
        raise RuntimeError("UNSAFE_DEFAULT:" + field)
loaded_forbidden = sorted(
    name
    for name in sys.modules
    if any(name == p or name.startswith(p + ".") for p in forbidden_prefixes)
)
if import_attempts or network_attempts or loaded_forbidden:
    raise RuntimeError("DEFAULT_SERVICE_ATTEMPTED_A_FORBIDDEN_EFFECT")
output = {
    "schema": "mpr2602.installed-default-observation.v1",
    "identity_schema": identity.MPR2602_PREPARED_PLAN_SCHEMA,
    "installed_module": str(Path(identity.__file__).resolve()),
    "working_directory": str(Path.cwd()),
    "exit_code": code,
    "report": report,
    "network_attempts": network_attempts,
    "forbidden_import_attempts": import_attempts,
    "loaded_forbidden_modules": loaded_forbidden,
    "requested_BLOCKED_EXTERNAL_observed": True,
    "full_mpr2602_completion_claimed": False,
    "live_readiness_claimed": False,
}
print(json.dumps(output, sort_keys=True, indent=2))
