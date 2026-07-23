"""Source-compatible module entrypoint for release evidence generation."""

from __future__ import annotations

from src.release_gate.mpr27_real_evidence import main


if __name__ == "__main__":
    raise SystemExit(main())
