"""Research storage.

Persists the Markdown report to ``<output_dir>/<topic>_report.md`` (the
documented convention) and a full machine-readable session snapshot to
``<sessions_dir>/<topic>_session.json`` so that a session remains inspectable and
a report is reproducible from stored data.
"""
from __future__ import annotations

import dataclasses
import json
import os
from enum import Enum

from research_engine.domain.models import ResearchSession
from research_engine.utils import safe_filename


class SessionStorage:
    """Writes reports and session snapshots to disk."""

    def __init__(self, output_dir: str = "report", sessions_dir: str = "sessions") -> None:
        self._output_dir = output_dir
        self._sessions_dir = sessions_dir

    def save_report(self, session: ResearchSession) -> str:
        """Write the report Markdown and return its path."""
        if session.report is None:
            raise ValueError("session has no report to save")
        os.makedirs(self._output_dir, exist_ok=True)
        filename = f"{safe_filename(session.request.topic)}_report.md"
        path = os.path.join(self._output_dir, filename)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(session.report.markdown)
        session.report.file_path = path
        return path

    def save_session(self, session: ResearchSession) -> str:
        """Write the full session snapshot as JSON and return its path."""
        os.makedirs(self._sessions_dir, exist_ok=True)
        filename = f"{safe_filename(session.request.topic)}_session.json"
        path = os.path.join(self._sessions_dir, filename)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(_to_serializable(session), handle, indent=2, ensure_ascii=False)
        return path


def serialize_session(session: ResearchSession) -> dict:
    """Public helper: convert a session to a JSON-safe dict.

    Used by the HTTP API to return a session as JSON without touching disk.
    """
    return _to_serializable(session)


def _to_serializable(session: ResearchSession) -> dict:
    """Convert a session (nested dataclasses/enums) to JSON-safe primitives."""
    return _convert(dataclasses.asdict(session))


def _convert(value):
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {k: _convert(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_convert(v) for v in value]
    return value
