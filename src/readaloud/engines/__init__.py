"""TTS engine: kokoro (local, offline). The single synthesis backend."""
from __future__ import annotations

from .base import Engine, EngineState, Voice
from .kokoro import KokoroEngine

__all__ = [
    "Engine",
    "EngineState",
    "Voice",
    "KokoroEngine",
    "build_engine",
]


def build_engine(config) -> KokoroEngine:
    """Instantiate the kokoro engine."""
    return KokoroEngine(config)
