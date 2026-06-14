"""Follow the active Claude session and surface each new assistant response.

The active session = the globally newest transcript by mtime, re-evaluated every
poll so it follows you across projects. We track seen message uuids; when the
active file *switches*, we adopt its current messages as the baseline and emit
nothing (otherwise switching sessions would dump that file's whole backlog).
"""
from __future__ import annotations

from pathlib import Path

from .transcript import assistant_messages, newest_transcript


class SessionWatcher:
    def __init__(self) -> None:
        self._seen: set[str] = set()
        self._file: Path | None = None

    def prime(self) -> None:
        """Mark everything currently present as already seen (read only NEW)."""
        f = newest_transcript()
        self._file = f
        if f:
            self._seen = {uuid for uuid, _ in assistant_messages(f)}

    def poll(self) -> list[tuple[str, str]]:
        """Return [(text, label)] for assistant responses not seen before."""
        f = newest_transcript()
        if f is None:
            return []
        msgs = assistant_messages(f)
        if f != self._file:
            # Session switched — rebaseline, don't replay this file's history.
            self._file = f
            self._seen = {uuid for uuid, _ in msgs}
            return []
        out: list[tuple[str, str]] = []
        for uuid, text in msgs:
            if uuid in self._seen:
                continue
            self._seen.add(uuid)
            out.append((text, "new response"))
        return out
