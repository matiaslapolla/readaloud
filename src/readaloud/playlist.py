"""Sequential read queue feeding the single audio driver.

Everything that wants to be spoken (preview, manual read, auto-watched responses)
is added here as a ReadJob. The app's reader loop pops jobs and plays them one at a
time. `interrupt=True` jumps the queue: it clears anything pending and sets the
preempt flag so the in-flight job stops at its next chunk boundary — that's how a
preview barges in over a long read.
"""
from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from typing import Callable


@dataclass
class ReadJob:
    text: str
    engine: str
    voice: str
    label: str
    words: int = 0
    chunks: int = 0  # streaming chunks — the progress denominator


class Playlist:
    def __init__(self) -> None:
        self._items: "deque[ReadJob]" = deque()
        self._cond = threading.Condition()
        self._now: ReadJob | None = None
        self._closed = False
        self.preempt = threading.Event()

    def add(self, job: ReadJob, interrupt: bool = False) -> None:
        with self._cond:
            if interrupt:
                self._items.clear()
                self.preempt.set()
            self._items.append(job)
            self._cond.notify()

    def pop(self, should_continue: Callable[[], bool], timeout: float = 0.2) -> ReadJob | None:
        """Block until a job is available (or cancelled/closed)."""
        with self._cond:
            while not self._items and not self._closed and should_continue():
                self._cond.wait(timeout)
            if self._closed or not should_continue() or not self._items:
                return None
            return self._items.popleft()

    def set_now(self, job: ReadJob | None) -> None:
        with self._cond:
            self._now = job

    def snapshot(self) -> tuple[ReadJob | None, list[str]]:
        with self._cond:
            return self._now, [j.label for j in self._items]

    def clear(self) -> None:
        with self._cond:
            self._items.clear()
            self.preempt.set()

    def close(self) -> None:
        with self._cond:
            self._closed = True
            self._cond.notify_all()
