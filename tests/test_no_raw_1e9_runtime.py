import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SCANNED_FILES = (
    Path("src/domain/cost_model.py"),
    Path("src/domain/money.py"),
    Path("scripts/paper_trader.py"),
)

def test_no_raw_1e9_arithmetic_in_migrated_runtime_paths():
    offenders = []
    for path in SCANNED_FILES:
        text = path.read_text()
        for idx, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if "1e9" in stripped and ("*" in stripped or "/" in stripped):
                offenders.append(f"{path}:{idx}:{stripped}")
    assert not offenders, "raw 1e9 arithmetic found in migrated runtime paths:\n" + "\n".join(offenders)
