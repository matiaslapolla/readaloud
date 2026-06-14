"""Headless engine core: config + speech + sequential read queue + reader thread.

No Textual here. Both the TUI (standalone) and the headless daemon embed one of
these and drive it identically. The IPC server talks to a core directly — the
Playlist is thread-safe (its own Condition), so there's no UI-thread hop to make.
A core is the single audio owner within its process.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable

from .config import Config
from .playlist import Playlist, ReadJob
from .speech import SpeechService
from .text import clean_for_speech, word_count


def _job_brief(job: ReadJob | None) -> dict | None:
    if job is None:
        return None
    return {"label": job.label, "engine": job.engine, "voice": job.voice, "words": job.words}


class ReadAloudCore:
    def __init__(self, config: Config | None = None) -> None:
        self.config = config or Config.load()
        self.speech = SpeechService(self.config)
        self.playlist = Playlist()
        self._stop = threading.Event()
        self._reader = threading.Thread(target=self._reader_loop, name="reader", daemon=True)
        self._autowatch = False
        self._watch_thread: threading.Thread | None = None
        self._now_cb: Callable[[ReadJob | None], None] | None = None

    # ---- lifecycle ----
    def start(self) -> None:
        self._reader.start()

    def warm_kokoro(self) -> None:
        """Blocking model load — call from a worker thread."""
        self.speech.warm_kokoro()

    def reload_config(self) -> None:
        """Re-read config.toml after the TUI edits it, keeping the warm model.

        Engines read their config live at synth time, so swapping the reference on
        the core, the speech service, and every engine is enough — nothing rebuilds,
        so the resident Kokoro pipelines stay loaded.
        """
        cfg = Config.load()
        self.config = cfg
        self.speech.config = cfg
        for engine in self.speech.engines.values():
            engine._config = cfg  # type: ignore[attr-defined]

    def shutdown(self) -> None:
        self._stop.set()
        self._autowatch = False
        self.playlist.close()
        self.speech.shutdown()

    def set_now_callback(self, cb: Callable[[ReadJob | None], None] | None) -> None:
        """UI hook: called with the now-playing job (or None) when it changes."""
        self._now_cb = cb

    def _set_now(self, job: ReadJob | None) -> None:
        self.playlist.set_now(job)
        if self._now_cb is not None:
            try:
                self._now_cb(job)
            except Exception:  # noqa: BLE001 — a bad UI callback must not kill the loop
                pass

    # ---- the single audio driver ----
    def _reader_loop(self) -> None:
        pl = self.playlist
        cont = lambda: not self._stop.is_set() and not pl.preempt.is_set()  # noqa: E731
        while not self._stop.is_set():
            job = pl.pop(lambda: not self._stop.is_set())
            if job is None:
                continue
            pl.preempt.clear()
            self._set_now(job)
            try:
                self.speech.synth_into_queue(job.engine, job.text, job.voice, cont)
                if cont():
                    self.speech.queue.wait_until_idle(cont)
            except Exception:  # noqa: BLE001 — one bad job shouldn't kill the loop
                pass
            self._set_now(None)

    # ---- job construction (thread-safe; no UI) ----
    def _resolve_engine(self) -> str:
        default = self.config.default_engine
        order = [default] + [n for n in self.config.engine_names() if n != default]
        for name in order:
            cfg = self.config.engine(name)
            if cfg.enabled and self.speech.engines[name].available():
                return name
        return "say"  # always available

    def _make_job(
        self, text: str, label: str, engine: str | None = None, voice: str | None = None
    ) -> ReadJob | None:
        if not text or not text.strip():
            return None
        engine = engine or self._resolve_engine()
        voice = self.speech.resolve_voice(engine, voice)
        return ReadJob(
            text=text,
            engine=engine,
            voice=voice,
            label=label,
            words=word_count(clean_for_speech(text)),
        )

    def read_last_job(self, cwd: str) -> ReadJob | None:
        from .transcript import last_assistant_text

        text, label = last_assistant_text(cwd)
        return self._make_job(text or "", label)

    def read_file_job(self, path: str) -> ReadJob | None:
        p = Path(path).expanduser()
        if not p.is_file():
            return None
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        return self._make_job(text, p.name)

    def read_text_job(self, text: str) -> ReadJob | None:
        return self._make_job(text, "text")

    # ---- enqueue entry points ----
    def enqueue(self, job: ReadJob | None, interrupt: bool = True) -> ReadJob | None:
        if job is not None:
            self.playlist.add(job, interrupt)
        return job

    def read_last(self, cwd: str, interrupt: bool = True) -> ReadJob | None:
        return self.enqueue(self.read_last_job(cwd), interrupt)

    def preview(self, engine: str, voice: str, text: str) -> ReadJob | None:
        return self.enqueue(self._make_job(text, "preview", engine, voice), True)

    def stop(self) -> None:
        self.playlist.clear()
        self.speech.stop()

    def status_dict(self) -> dict:
        now, pending = self.playlist.snapshot()
        return {
            "playing": _job_brief(now),
            "queue": pending,
            "kokoro": self.speech.engine_state("kokoro").value,
            "autowatch": self._autowatch,
        }

    def is_busy(self) -> bool:
        now, pending = self.playlist.snapshot()
        return now is not None or bool(pending)

    # ---- auto-watch ----
    def set_autowatch(self, on: bool) -> None:
        self._autowatch = on
        if on and (self._watch_thread is None or not self._watch_thread.is_alive()):
            self._watch_thread = threading.Thread(
                target=self._watch_loop, name="watch", daemon=True
            )
            self._watch_thread.start()

    def _watch_loop(self) -> None:
        from .watcher import SessionWatcher

        watcher = SessionWatcher()
        watcher.prime()
        while not self._stop.is_set() and self._autowatch:
            for text, label in watcher.poll():
                job = self._make_job(text, label)
                if job:
                    self.playlist.add(job, False)
            for _ in range(15):  # ~1.5s, but stay responsive to cancel/toggle
                if self._stop.is_set() or not self._autowatch:
                    return
                time.sleep(0.1)
