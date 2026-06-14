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
from .engines import build_engines
from .engines.base import EngineState
from .playback import AudioQueue
from .text import clean_for_speech

_TMP_PREFIX = "readaloud."
_STALE_SECONDS = 30 * 60


class SpeechService:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.engines = build_engines(config)
        self.queue = AudioQueue()
        _sweep_stale_tmp()
        self.tmpdir = Path(tempfile.mkdtemp(prefix=_TMP_PREFIX))

    # ---- engine helpers ----
    def warm_kokoro(self) -> None:
        self.engines["kokoro"].warm()

    def engine_state(self, name: str) -> EngineState:
        return self.engines[name].state()

    def resolve_voice(self, engine_name: str, voice: str | None) -> str:
        """Apply the READ_ALOUD_VOICE pin / engine default when none is given."""
        if voice:
            return voice
        if self.config.pinned_voice:
            return self.config.pinned_voice
        return self.config.engine(engine_name).default_voice

    # ---- synthesis ----
    def synth_into_queue(
        self,
        engine_name: str,
        text: str,
        voice: str,
        should_continue: Callable[[], bool],
    ) -> None:
        """Blocking: synthesize chunk-by-chunk into the audio queue.

        Call from a worker thread. `should_continue()` is polled between chunks for
        cooperative cancellation (a fresh speak also bumps the queue epoch, so any
        in-flight chunk is dropped even mid-synth).
        """
        engine = self.engines[engine_name]
        spoken = clean_for_speech(text)
        if not spoken.strip():
            return
        epoch = self.queue.new_epoch()
        workdir = self.tmpdir / f"s{epoch}"
        workdir.mkdir(parents=True, exist_ok=True)
        for path in engine.synth_chunks(spoken, voice, workdir):
            if not should_continue() or epoch != self.queue.current_epoch:
                break
            self.queue.enqueue(epoch, path)

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
