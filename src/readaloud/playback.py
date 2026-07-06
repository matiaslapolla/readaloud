"""Ordered audio playback via afplay, with backpressure and clean barge-in.

One AudioQueue per app. Engines synthesize chunk files and enqueue them; a single
player thread afplays them in order. Each logical "speak" gets an epoch — calling
`interrupt()` bumps the epoch, kills the current afplay, and makes the player drop
any already-queued chunks from the old epoch. This is how pressing preview on a new
voice instantly stops the previous one.
"""
from __future__ import annotations

import os
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable


class AudioQueue:
    def __init__(self, maxsize: int = 4) -> None:
        # (epoch, path, cleanup, chunk_index)
        self._q: "queue.Queue[tuple[int, Path, bool, int] | None]" = queue.Queue(maxsize=maxsize)
        self._epoch = 0
        self._epoch_lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._proc_lock = threading.Lock()
        # Progress, tracked at text-chunk granularity for the current read.
        self._prog_lock = threading.Lock()
        self._prog_epoch = 0
        self._total = 0
        self._playing = -1  # index of the chunk whose audio is on afplay right now
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    @property
    def current_epoch(self) -> int:
        with self._epoch_lock:
            return self._epoch

    def new_epoch(self) -> int:
        """Start a fresh playback generation, interrupting the previous one."""
        self.interrupt()
        with self._epoch_lock:
            self._epoch += 1
            return self._epoch

    def begin(self, epoch: int, total: int) -> None:
        """Register the chunk total for a fresh read so progress has a denominator.

        Called right after new_epoch(), before the first chunk is enqueued.
        """
        with self._prog_lock:
            self._prog_epoch = epoch
            self._total = total
            self._playing = -1

    def progress(self) -> "dict | None":
        """Current read position, or None when idle / between reads.

        `chunk` counts chunks whose playback has started (1..chunks); it reaches
        `chunks` only once the last chunk is actually playing.
        """
        cur = self.current_epoch
        with self._prog_lock:
            if self._prog_epoch != cur or self._total <= 0:
                return None
            played = min(self._playing + 1, self._total)
            return {"chunk": max(0, played), "chunks": self._total}

    def _mark_playing(self, epoch: int, chunk_index: int) -> None:
        with self._prog_lock:
            if epoch == self._prog_epoch:
                self._playing = chunk_index

    def interrupt(self) -> None:
        """Stop current audio and discard everything still queued."""
        with self._epoch_lock:
            self._epoch += 1  # invalidate queued + in-flight items
        # Drain pending items.
        while True:
            try:
                item = self._q.get_nowait()
            except queue.Empty:
                break
            if item is not None:
                _, path, cleanup, _ = item
                if cleanup:
                    _safe_remove(path)
        # Kill whatever is playing.
        with self._proc_lock:
            if self._proc and self._proc.poll() is None:
                self._proc.terminate()

    def enqueue(self, epoch: int, path: Path, chunk_index: int = 0, cleanup: bool = True) -> None:
        """Queue a chunk for playback. Drops it if its epoch is already stale."""
        if epoch != self.current_epoch:
            if cleanup:
                _safe_remove(path)
            return
        self._q.put((epoch, path, cleanup, chunk_index))

    def wait_until_idle(self, should_continue: "Callable[[], bool]", poll: float = 0.1) -> None:
        """Block until nothing is queued or playing (used to read jobs sequentially).

        Precondition: the producer has finished enqueuing. The double-check covers
        the brief dequeue→Popen gap so we don't report idle mid-handoff. Returns
        early if should_continue() goes False (e.g. a preempting read arrived).
        """
        while should_continue():
            if self._is_idle():
                time.sleep(poll)
                if self._is_idle():
                    return
            time.sleep(poll)

    def _is_idle(self) -> bool:
        with self._proc_lock:
            playing = self._proc is not None and self._proc.poll() is None
        return self._q.empty() and not playing

    def _run(self) -> None:
        while True:
            item = self._q.get()
            if item is None:
                continue
            epoch, path, cleanup, chunk_index = item
            if epoch != self.current_epoch:
                if cleanup:
                    _safe_remove(path)
                continue
            self._mark_playing(epoch, chunk_index)
            try:
                proc = subprocess.Popen(
                    ["afplay", str(path)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                with self._proc_lock:
                    self._proc = proc
                proc.wait()
            except Exception:
                pass
            finally:
                with self._proc_lock:
                    self._proc = None
                if cleanup:
                    _safe_remove(path)


def _safe_remove(path: Path) -> None:
    try:
        os.remove(path)
    except OSError:
        pass
