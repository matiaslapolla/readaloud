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

# Pipeline "profiles". A profile is normally just a kokoro lang code, but a profile
# may append an espeak-ng language override (after a '-') to re-accent that lang.
# Kokoro hardcodes lang 'e' -> Castilian espeak 'es'; 'e-419' swaps the g2p to
# 'es-419' (Latin-American Spanish: seseo + yeísmo) while reusing the same voices.
_ESPEAK_OVERRIDE = {"e-419": "es-419"}

# Curated voices: display id -> (kokoro voice pack, pipeline profile, note).
# Kokoro ships only three Spanish packs (ef_dora, em_alex, em_santa), all lang 'e';
# we expose each in two accents by pairing it with the 'e' or 'e-419' profile.
_VOICE_SPECS: dict[str, tuple[str, str, str]] = {
    "af_heart": ("af_heart", "a", "US · female"),
    "af_bella": ("af_bella", "a", "US · female"),
    "af_nicole": ("af_nicole", "a", "US · female"),
    "am_michael": ("am_michael", "a", "US · male"),
    "am_fenrir": ("am_fenrir", "a", "US · male"),
    "bf_emma": ("bf_emma", "b", "UK · female"),
    "bm_george": ("bm_george", "b", "UK · male"),
    # Spanish — Castilian (espeak 'es')
    "ef_dora": ("ef_dora", "e", "ES · female"),
    "em_alex": ("em_alex", "e", "ES · male"),
    "em_santa": ("em_santa", "e", "ES · male"),
    # Spanish — Latin American (espeak 'es-419'; seseo + yeísmo)
    "ef_dora_latam": ("ef_dora", "e-419", "LATAM · female"),
    "em_alex_latam": ("em_alex", "e-419", "LATAM · male"),
    "em_santa_latam": ("em_santa", "e-419", "LATAM · male"),
}

_VOICE_NOTES = {vid: spec[2] for vid, spec in _VOICE_SPECS.items()}


def _resolve_voice(voice: str) -> tuple[str, str]:
    """Map a display voice id to (kokoro voice pack, pipeline profile).

    Unknown ids fall back to the old convention: the id is the kokoro voice and
    its first letter is the lang code (so custom/user voices keep working).
    """
    spec = _VOICE_SPECS.get(voice)
    if spec:
        return spec[0], spec[1]
    profile = voice[0] if voice[:1] in _LANGS else "a"
    return voice, profile


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

    def _pipeline(self, profile: str):
        with self._lock:
            if profile not in self._pipelines:
                from kokoro import KPipeline  # heavy import — happens once

                base = profile.split("-", 1)[0]  # 'e-419' -> 'e'
                pipe = KPipeline(lang_code=base)
                espeak_lang = _ESPEAK_OVERRIDE.get(profile)
                if espeak_lang:
                    from misaki.espeak import EspeakG2P

                    pipe.g2p = EspeakG2P(language=espeak_lang)
                self._pipelines[profile] = pipe
            return self._pipelines[profile]

    # ---- voices ----
    def list_voices(self) -> list[Voice]:
        return [Voice(id=v, label=v, note=_VOICE_NOTES.get(v, "")) for v in self._config.voices]

    # ---- synthesis ----
    def synth_chunk(self, chunk: str, voice: str, workdir: Path, seq: int) -> Iterator[Path]:
        import soundfile as sf

        kvoice, profile = _resolve_voice(voice)
        pipe = self._pipeline(profile)  # cached per profile — cheap to fetch per chunk
        self._state = EngineState.READY
        # Kokoro splits a chunk into its own segments; they all belong to chunk seq.
        for sub, (_, _, audio) in enumerate(pipe(chunk, voice=kvoice)):
            wav = workdir / f"seg_{seq}_{sub}.wav"
            sf.write(str(wav), audio, 24000)
            yield wav
