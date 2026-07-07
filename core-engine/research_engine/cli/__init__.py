"""Terminal interfaces (Layer 1).

The ``cli`` package holds every terminal-facing surface: the plain,
non-interactive CLI (``cli.app``) and the animated live dashboard
(``cli.tui``). Both share one argument parser and config wiring and depend
*downward* on the engine only — no research logic lives here.

``main`` is re-exported so the ``research-engine`` console script and
``python -m research_engine`` keep resolving to ``research_engine.cli:main``
after the module→package split.
"""
from __future__ import annotations

from research_engine.cli.app import (
    build_arg_parser,
    config_from_args,
    main,
    run,
)

__all__ = ["build_arg_parser", "config_from_args", "main", "run"]
