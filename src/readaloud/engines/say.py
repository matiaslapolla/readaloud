"""macOS `say` engine — offline, always available, robotic. Auto-fallback path.

Synthesizes to AIFF files with `say -o` (verified to produce audio on this Mac,
unlike `say -f`) so it plugs into the same afplay queue as the other engines —
which also sidesteps the gotcha where a backgrounded inline `say` gets reaped.
Voice list is enumerated live from `say -v '?'` so it reflects what's installed.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Iterator

from ..config import Config
from ..text import chunk_text
from .base import EngineState, Voice

# Decent standard voices worth surfacing alongside any installed Enhanced/Premium.
_CURATED = {
    "Samantha", "Daniel", "Karen", "Moira", "Tessa", "Allison", "Ava", "Zoe",
    "Tom", "Nathan", "Susan", "Evan", "Joelle", "Nicky", "Aaron",
}
_LINE = re.compile(r"^(?P<name>.+?)\s{2,}(?P<lang>[a-zA-Z_\-]+)\s+#\s*(?P<note>.*)$")


class SayEngine:
    name = "say"
    privacy = "local"

    def __init__(self, config: Config) -> None:
        self._config = config
        self._voices_cache: list[Voice] | None = None

    def available(self) -> bool:
        return True  # built into macOS

    def state(self) -> EngineState:
        return EngineState.READY

    def list_voices(self) -> list[Voice]:
        if self._voices_cache is None:
            self._voices_cache = _enumerate_say_voices()
        return self._voices_cache

    def synth_chunks(self, text: str, voice: str, workdir: Path) -> Iterator[Path]:
        rate = self._config.say_rate
        idx = 0
        for chunk in chunk_text(text, max_chars=600):
            aiff = workdir / f"seg_{idx}.aiff"
            cmd = ["say", "-o", str(aiff), "-r", str(rate)]
            if voice:
                cmd += ["-v", voice]
            cmd.append(chunk)
            try:
                subprocess.run(cmd, check=False, stderr=subprocess.DEVNULL)
            except Exception:
                continue
            if aiff.exists() and aiff.stat().st_size > 0:
                yield aiff
                idx += 1


def _enumerate_say_voices() -> list[Voice]:
    try:
        out = subprocess.run(
            ["say", "-v", "?"], check=False, capture_output=True, text=True
        ).stdout
    except Exception:
        return [Voice(id="Samantha", label="Samantha", note="")]

    voices: list[Voice] = []
    seen: set[str] = set()
    for line in out.splitlines():
        m = _LINE.match(line)
        if not m:
            continue
        raw = m.group("name").strip()
        lang = m.group("lang").strip()
        # Name may carry a quality tag, e.g. "Ava (Premium)".
        qual = ""
        base = raw
        qm = re.match(r"^(.*?)\s*\((Enhanced|Premium)\)\s*$", raw)
        if qm:
            base, qual = qm.group(1), qm.group(2)
        keep = qual in ("Enhanced", "Premium") or base in _CURATED
        if not keep or raw in seen:
            continue
        seen.add(raw)
        note = " · ".join(p for p in (lang, qual) if p)
        voices.append(Voice(id=raw, label=raw, note=note))
    voices.sort(key=lambda v: v.label.lower())
    return voices or [Voice(id="Samantha", label="Samantha", note="")]
