#!/usr/bin/env python3
"""Zero-install entry point for the Research Engine.

Running ``python main.py "<topic>"`` puts the ``core-engine`` source directory on
the import path and delegates to :func:`research_engine.cli.main`. For an
installed package, use the ``research-engine`` console script instead.
"""
from __future__ import annotations

import os
import sys

_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "core-engine")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from research_engine.cli import main  # noqa: E402  (import after path setup)

if __name__ == "__main__":
    raise SystemExit(main())
