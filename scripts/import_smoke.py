from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import src.application  # noqa: E402,F401
import src.execution.live_control  # noqa: E402,F401

print("import smoke ok")
