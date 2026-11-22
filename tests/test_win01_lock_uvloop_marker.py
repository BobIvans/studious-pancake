"""WIN-01 regression: requirements.lock keeps the uvloop Windows marker.

The lock generator (scripts/lock_requirements.py) must re-apply the
``platform_system != 'Windows'`` marker of the direct ``uvloop`` pin from
``pyproject.toml`` to the compiled lock artifacts, so that hash-verified
installs resolve on Windows without pulling uvloop (which has no Windows
wheel). Defect: WINDOWS_LOCK_UVLOOP_NO_MARKER.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
PIN_RE = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s;]+)\s*(.*)$")
UVLOOP_MARKER = "platform_system != 'Windows'"


def _uvloop_lock_line(lock_name: str) -> str:
    for raw in (ROOT / lock_name).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if PIN_RE.match(line) and line.lower().startswith("uvloop=="):
            return line
    raise AssertionError(f"uvloop pin not found in {lock_name}")


def test_uvloop_lock_pins_carry_windows_excluding_marker() -> None:
    for lock_name in ("requirements.lock", "requirements-dev.lock"):
        line = _uvloop_lock_line(lock_name)
        match = PIN_RE.match(line)
        assert match is not None, line
        assert match.group(2) == "0.22.1", line
        assert UVLOOP_MARKER in line, line


def test_lock_hash_blocks_are_intact() -> None:
    for lock_name in ("requirements.lock", "requirements-dev.lock"):
        text = (ROOT / lock_name).read_text(encoding="utf-8")
        assert text.count("--hash=sha256:") > 100, lock_name


def test_uvloop_is_the_only_marker_bearing_direct_dependency() -> None:
    # The generator re-applies markers of direct dependencies only; this
    # assertion documents that uvloop is the sole marker-bearing pin today.
    with (ROOT / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)["project"]
    values = list(project.get("dependencies") or [])
    optional = project.get("optional-dependencies") or {}
    for group in ("analytics", "service", "dev"):
        values.extend(optional.get(group) or [])
    marked = [v for v in values if ";" in str(v)]
    assert marked == [f"uvloop==0.22.1; {UVLOOP_MARKER}"], marked


def test_generator_contains_marker_reapplication_mechanism() -> None:
    script = (ROOT / "scripts/lock_requirements.py").read_text(encoding="utf-8")
    assert "_reapply_direct_markers" in script
    assert "_reapply_direct_markers(output, project)" in script
