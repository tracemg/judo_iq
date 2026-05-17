#!/usr/bin/env python3
"""CLI entrypoint for the JudoIQ analyzer."""

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from analyzers.judo_analyzer import analyze, main


__all__ = ["analyze", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
