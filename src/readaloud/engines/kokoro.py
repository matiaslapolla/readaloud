"""Kokoro engine — local, offline, private. The reason this app exists resident.

The model load (torch + spaCy + weights) costs ~8-13s, so we do it ONCE in a
background warmup and keep the KPipeline(s) resident for the life of the app. After
warmup, time-to-first-audio is dominated by synthesizing the first short chunk.
Ported from the prototype's kokoro_synth.py.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Iterator

from ..config import Config
from .base import EngineState, Voice

# kokoro lang codes; a voice name's first letter selects one (a=US, b=UK, e=ES…).
_LANGS = set("abefhijpz")

_VOICE_NOTES = {
    "af_heart": "US · female",
    "af_bella": "US · female",
    "af_nicole": "US · female",
    "am_michael": "US · male",
    "am_fenrir": "US · male",
    "bf_emma": "UK · female",
    "bm_george": "UK · male",
}


class KokoroEngine:
    name = "kokoro"
    privacy = "local"

    def __init__(self, config: Config) -> None:
        self._config = config
        self._pipelines: dict[str, object] = {}  # lang_code -> KPipeline
        self._lock = threading.Lock()
        self._state = EngineState.WARMING
        self._import_ok: bool | None = None

    # ---- availability / readiness ----
    def available(self) -> bool:
        if self._import_ok is None:
            try:
                import kokoro  # noqa: F401
                import soundfile  # noqa: F401

                self._import_ok = True
            except Exception:
                self._import_ok = False
                self._state = EngineState.UNAVAILABLE
        return self._import_ok

    def state(self) -> EngineState:
        return self._state

    def warm(self) -> None:
        """Blocking: load the model + default pipeline. Call from a worker thread."""
        if not self.available():
            return
        try:
            self._pipeline("a")  # American English — the common case
            self._state = EngineState.READY
        except Exception:
            self._state = EngineState.UNAVAILABLE

    def _pipeline(self, lang: str):
        with self._lock:
            if lang not in self._pipelines:
                from kokoro import KPipeline  # heavy import — happens once

                self._pipelines[lang] = KPipeline(lang_code=lang)
            return self._pipelines[lang]

    # ---- voices ----
    def list_voices(self) -> list[Voice]:
        return [Voice(id=v, label=v, note=_VOICE_NOTES.get(v, "")) for v in self._config.voices]

    # ---- synthesis ----
    def synth_chunk(self, chunk: str, voice: str, workdir: Path, seq: int) -> Iterator[Path]:
        import soundfile as sf

        lang = voice[0] if voice[:1] in _LANGS else "a"
        pipe = self._pipeline(lang)  # cached per lang — cheap to fetch per chunk
        self._state = EngineState.READY
        # Kokoro splits a chunk into its own segments; they all belong to chunk seq.
        for sub, (_, _, audio) in enumerate(pipe(chunk, voice=voice)):
            wav = workdir / f"seg_{seq}_{sub}.wav"
            sf.write(str(wav), audio, 24000)
            yield wav
