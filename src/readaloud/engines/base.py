"""Engine protocol shared by kokoro / edge / say.

An engine knows how to enumerate its voices and synthesize text into a sequence of
audio files (one per chunk, in order). It does NOT play audio — the AudioQueue owns
playback. Engines yield file paths as soon as each chunk is ready so the queue can
start playing chunk N while chunk N+1 synthesizes.
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

    def synth_chunks(self, text: str, voice: str, workdir: Path) -> Iterator[Path]:
        """Yield audio file paths in playback order, one per text chunk.

        Generators are consumed from a worker thread; cooperative cancellation is
        the caller's job (stop iterating). Each yielded file is owned by the caller
        (the AudioQueue removes it after playing).
        """
