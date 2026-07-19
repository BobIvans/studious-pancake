#!/usr/bin/env python3
"""PR-023 QUARANTINE: legacy wrapper; use `python arb_bot.py status`."""
import sys
import os

# Forward execution to the actual script in the scripts/ folder
actual_script = os.path.join(os.path.dirname(__file__), "scripts", "paper_trader.py")
if os.path.exists(actual_script):
    os.execv(sys.executable, [sys.executable, actual_script] + sys.argv[1:])
else:
    print(f"Error: actual paper trader script not found at {actual_script}", file=sys.stderr)
    sys.exit(1)
