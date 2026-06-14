"""Edge engine — Microsoft neural voices. Fast (~2-3s) but CLOUD: text is sent to
Microsoft's servers. The UI surfaces this; `allow_edge=false` disables it.

Uses the edge_tts library's Communicate API directly (one request per chunk) so we
stream audio the same way as kokoro. Ported from the prototype's edge driver.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Iterator

from ..config import Config
from ..text import chunk_text
from .base import EngineState, Voice

_VOICE_NOTES = {
    "en-US-AvaMultilingualNeural": "US · female · multilingual",
    "en-US-AndrewMultilingualNeural": "US · male · multilingual",
    "en-US-EmmaMultilingualNeural": "US · female · multilingual",
    "en-US-BrianMultilingualNeural": "US · male · multilingual",
    "en-US-AriaNeural": "US · female",
    "en-US-GuyNeural": "US · male",
    "en-US-JennyNeural": "US · female",
}


class EdgeEngine:
    name = "edge"
    privacy = "cloud"

    def __init__(self, config: Config) -> None:
        self._config = config
        self._import_ok: bool | None = None

    def available(self) -> bool:
        if not self._config.allow_edge:
            return False
        if self._import_ok is None:
            try:
                import edge_tts  # noqa: F401

                self._import_ok = True
            except Exception:
                self._import_ok = False
        return self._import_ok

    def state(self) -> EngineState:
        if not self._config.allow_edge or not self.available():
            return EngineState.UNAVAILABLE
        return EngineState.READY  # no warmup needed

    def list_voices(self) -> list[Voice]:
        cfg = self._config.engine("edge")
        return [Voice(id=v, label=v, note=_VOICE_NOTES.get(v, "")) for v in cfg.voices]

    def synth_chunks(self, text: str, voice: str, workdir: Path) -> Iterator[Path]:
        import edge_tts

        rate = self._config.edge_rate
        idx = 0
        for chunk in chunk_text(text, max_chars=600):
            mp3 = workdir / f"seg_{idx}.mp3"
            try:
                asyncio.run(_synth_one(chunk, voice, rate, mp3))
            except Exception:
                continue
            if mp3.exists() and mp3.stat().st_size > 0:
                yield mp3
                idx += 1


async def _synth_one(text: str, voice: str, rate: str, out: Path) -> None:
    import edge_tts

    communicate = edge_tts.Communicate(text, voice, rate=rate)
    await communicate.save(str(out))
