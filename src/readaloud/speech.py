"""Speech orchestration — ties engines to the audio queue. No Textual here.

The Textual layer wraps these blocking calls in workers; this module stays a plain,
testable service (data/engine layer separate from UI). One temp dir per app run;
chunk files self-clean after playback, the dir is removed on shutdown, and stale
dirs from killed past runs are swept at startup (ported from the prototype).
"""
from __future__ import annotations

import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Callable

from .config import Config
from .engines import build_engine
from .engines.base import EngineState
from .playback import AudioQueue
from .text import chunk_text, clean_for_speech

_TMP_PREFIX = "readaloud."
_STALE_SECONDS = 30 * 60


class SpeechService:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.engine = build_engine(config)
        self.queue = AudioQueue()
        _sweep_stale_tmp()
        self.tmpdir = Path(tempfile.mkdtemp(prefix=_TMP_PREFIX))

    # ---- engine helpers ----
    def warm_kokoro(self) -> None:
        self.engine.warm()

    def engine_state(self) -> EngineState:
        return self.engine.state()

    def resolve_voice(self, voice: str | None) -> str:
        """Apply the READ_ALOUD_VOICE pin / configured default when none is given."""
        if voice:
            return voice
        if self.config.pinned_voice:
            return self.config.pinned_voice
        return self.config.default_voice

    # ---- synthesis ----
    def synth_into_queue(
        self,
        text: str,
        voice: str,
        should_continue: Callable[[], bool],
    ) -> None:
        """Blocking: synthesize chunk-by-chunk into the audio queue.

        Call from a worker thread. `should_continue()` is polled between chunks for
        cooperative cancellation (a fresh speak also bumps the queue epoch, so any
        in-flight chunk is dropped even mid-synth).
        """
        engine = self.engine
        spoken = clean_for_speech(text)
        if not spoken.strip():
            return
        chunks = chunk_text(spoken)
        epoch = self.queue.new_epoch()
        self.queue.begin(epoch, len(chunks))  # total is the progress denominator
        workdir = self.tmpdir / f"s{epoch}"
        workdir.mkdir(parents=True, exist_ok=True)
        for i, chunk in enumerate(chunks):
            if not should_continue() or epoch != self.queue.current_epoch:
                break
            for path in engine.synth_chunk(chunk, voice, workdir, i):
                if not should_continue() or epoch != self.queue.current_epoch:
                    break
                self.queue.enqueue(epoch, path, i)

    def stop(self) -> None:
        self.queue.interrupt()

    def shutdown(self) -> None:
        self.queue.interrupt()
        shutil.rmtree(self.tmpdir, ignore_errors=True)


def _sweep_stale_tmp() -> None:
    """Remove readaloud temp dirs older than 30 min (never an in-flight run)."""
    root = Path(tempfile.gettempdir())
    now = time.time()
    try:
        for p in root.glob(f"{_TMP_PREFIX}*"):
            try:
                if p.is_dir() and now - p.stat().st_mtime > _STALE_SECONDS:
                    shutil.rmtree(p, ignore_errors=True)
            except OSError:
                pass
    except OSError:
        pass
