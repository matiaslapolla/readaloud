"""TTS engines: kokoro (local), edge (cloud), say (local fallback)."""
from __future__ import annotations

from .base import Engine, EngineState, Voice
from .edge import EdgeEngine
from .kokoro import KokoroEngine
from .say import SayEngine

__all__ = [
    "Engine",
    "EngineState",
    "Voice",
    "KokoroEngine",
    "EdgeEngine",
    "SayEngine",
    "build_engines",
]


def build_engines(config) -> dict[str, Engine]:
    """Instantiate every engine, keyed by name."""
    return {
        "kokoro": KokoroEngine(config),
        "edge": EdgeEngine(config),
        "say": SayEngine(config),
    }
