"""User config + curated voice lists, persisted as TOML in the project dir.

Lives next to the code (the project's chosen layout). The live file `config.toml`
is gitignored; `config.example.toml` is committed as a template. Environment
variables (READ_ALOUD_*) still win at runtime so the old alias workflow keeps
behaving identically.
"""
from __future__ import annotations

import copy
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tomli_w

# project root = .../readaloud  (src/readaloud/config.py -> parents[2])
PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config.toml"
EXAMPLE_PATH = PROJECT_ROOT / "config.example.toml"

# Engine ordering = fallback preference (first available wins when unset).
ENGINE_ORDER = ("kokoro", "edge", "say")

DEFAULTS: dict[str, Any] = {
    "default_engine": "kokoro",
    "allow_edge": True,  # privacy: edge sends text to Microsoft's servers
    "sample_text": "The quick brown fox jumps over the lazy dog. "
    "Pack my box with five dozen liquor jugs.",
    "edge_rate": "+15%",
    "say_rate": 240,
    "engines": {
        "kokoro": {
            "enabled": True,
            "default_voice": "af_heart",
            # a=US, b=UK; f/m = female/male. Pin an ef_* voice for Spanish.
            "voices": [
                "af_heart",
                "af_bella",
                "af_nicole",
                "am_michael",
                "am_fenrir",
                "bf_emma",
                "bm_george",
            ],
        },
        "edge": {
            "enabled": True,
            "default_voice": "en-US-AvaMultilingualNeural",
            # The *Multilingual* voices also read ES/PT well.
            "voices": [
                "en-US-AvaMultilingualNeural",
                "en-US-AndrewMultilingualNeural",
                "en-US-EmmaMultilingualNeural",
                "en-US-BrianMultilingualNeural",
                "en-US-AriaNeural",
                "en-US-GuyNeural",
                "en-US-JennyNeural",
            ],
        },
        "say": {
            "enabled": True,
            "default_voice": "",  # empty => random from the installed curated pool
            "voices": [],  # populated live from `say -v '?'`; see engines/say.py
        },
    },
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


@dataclass
class EngineConfig:
    name: str
    enabled: bool
    default_voice: str
    voices: list[str] = field(default_factory=list)


class Config:
    """Loaded config with env overrides applied at read time."""

    def __init__(self, data: dict[str, Any]):
        self._data = data

    # ---- load / save ----
    @classmethod
    def load(cls) -> "Config":
        data = copy.deepcopy(DEFAULTS)
        if CONFIG_PATH.exists():
            with CONFIG_PATH.open("rb") as fh:
                data = _deep_merge(data, tomllib.load(fh))
        return cls(data)

    def save(self) -> None:
        with CONFIG_PATH.open("wb") as fh:
            tomli_w.dump(self._data, fh)

    # ---- top-level accessors (env overrides win) ----
    @property
    def default_engine(self) -> str:
        return os.environ.get("READ_ALOUD_ENGINE") or self._data["default_engine"]

    @default_engine.setter
    def default_engine(self, value: str) -> None:
        self._data["default_engine"] = value

    @property
    def allow_edge(self) -> bool:
        return bool(self._data["allow_edge"])

    @allow_edge.setter
    def allow_edge(self, value: bool) -> None:
        self._data["allow_edge"] = bool(value)

    @property
    def sample_text(self) -> str:
        return self._data["sample_text"]

    @sample_text.setter
    def sample_text(self, value: str) -> None:
        self._data["sample_text"] = value

    @property
    def edge_rate(self) -> str:
        return os.environ.get("READ_ALOUD_EDGE_RATE") or self._data["edge_rate"]

    @property
    def say_rate(self) -> int:
        env = os.environ.get("READ_ALOUD_RATE")
        return int(env) if env else int(self._data["say_rate"])

    @property
    def pinned_voice(self) -> str | None:
        """READ_ALOUD_VOICE pins a single voice across engines (alias parity)."""
        return os.environ.get("READ_ALOUD_VOICE") or None

    # ---- per-engine ----
    def engine(self, name: str) -> EngineConfig:
        e = self._data["engines"][name]
        return EngineConfig(
            name=name,
            enabled=bool(e.get("enabled", True)),
            default_voice=e.get("default_voice", ""),
            voices=list(e.get("voices", [])),
        )

    def set_engine_enabled(self, name: str, enabled: bool) -> None:
        self._data["engines"][name]["enabled"] = bool(enabled)

    def set_engine_default_voice(self, name: str, voice: str) -> None:
        self._data["engines"][name]["default_voice"] = voice

    def set_engine_voices(self, name: str, voices: list[str]) -> None:
        self._data["engines"][name]["voices"] = list(voices)

    def engine_names(self) -> list[str]:
        return [n for n in ENGINE_ORDER if n in self._data["engines"]]

    def raw(self) -> dict[str, Any]:
        return self._data
