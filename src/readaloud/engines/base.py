"""Engine protocol implemented by kokoro (the only backend).

Kept as a protocol so synthesis stays a clean seam behind the UI/config layers.
An engine knows how to enumerate its voices and synthesize ONE text chunk into a
sequence of audio files (in order). It does NOT play audio — the AudioQueue owns
playback. The speech layer owns chunking now (so the total chunk count — the
progress denominator — is known before synthesis starts) and feeds chunks in one
at a time. Engines yield file paths as soon as each is ready so the queue can start
playing chunk N while chunk N+1 synthesizes.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterator, Protocol, runtime_checkable


class EngineState(str, Enum):
    READY = "ready"
    WARMING = "warming"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class Voice:
    id: str  # value passed to the engine, e.g. "af_heart" / "en-US-AriaNeural"
    label: str  # human-friendly display label
    note: str = ""  # e.g. "US · female" or "Enhanced"


@runtime_checkable
class Engine(Protocol):
    name: str
    privacy: str  # "local" | "cloud"

    def available(self) -> bool:
        """Whether this engine can run at all on this machine."""

    def state(self) -> EngineState:
        """Current readiness — drives the 'warming…' badge in the UI."""

    def list_voices(self) -> list[Voice]:
        """Curated/available voices for the picker."""

    def synth_chunk(self, chunk: str, voice: str, workdir: Path, seq: int) -> Iterator[Path]:
        """Yield audio file paths in playback order for a single text chunk.

        `seq` is the chunk's index in the whole read — use it to name files so
        chunks don't collide in the shared workdir. An engine may yield more than
        one file for a chunk (Kokoro splits internally); all of them belong to
        chunk `seq`. Generators are consumed from a worker thread; cooperative
        cancellation is the caller's job (stop iterating). Each yielded file is
        owned by the caller (the AudioQueue removes it after playing).
        """
