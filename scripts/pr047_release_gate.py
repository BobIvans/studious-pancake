#!/usr/bin/env python3
"""Thin executable wrapper for the PR-047 release gate."""

from src.release_gate.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
