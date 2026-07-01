"""Put the ``core-engine`` source directory on the import path for tests.

Importing this module (``from tests import _path``) is enough; it mutates
``sys.path`` as a side effect so tests can ``import research_engine`` without an
installed package.
"""
from __future__ import annotations

import os
import sys

_SRC = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core-engine"
)
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
