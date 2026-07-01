"""Centralized logging configuration.

A single helper keeps log formatting consistent across subsystems and avoids
each module configuring the root logger independently.
"""
from __future__ import annotations

import logging

_CONFIGURED = False


def configure_logging(level: str = "INFO") -> None:
    """Configure the root logger once, idempotently."""
    global _CONFIGURED
    numeric = getattr(logging, level.upper(), logging.INFO)
    if _CONFIGURED:
        logging.getLogger().setLevel(numeric)
        return
    logging.basicConfig(
        level=numeric,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger for a subsystem."""
    return logging.getLogger(f"research_engine.{name}")
