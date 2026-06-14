# /// script
# requires-python = ">=3.10"
# dependencies = ["kokoro>=0.9.4", "soundfile", "numpy"]
# ///
"""Kokoro streaming synth+player for read-aloud (engine: kokoro).

Usage:  kokoro_synth.py <voice> <workdir>
  <workdir>/text.txt  -> text to speak
  writes <workdir>/ok after the first segment plays (caller liveness signal)

Loads the model ONCE, then overlaps generation with playback: a player thread
afplays segments in order while the main thread keeps synthesizing (bounded queue
provides backpressure). Stopped by: pkill -f kokoro_synth.py (+ pkill afplay).
"""
import os
import queue
import re
import subprocess
import sys
import threading

LANGS = set("abefhijpz")  # kokoro lang codes; voice name's first letter selects one


def chunk_text(text, max_chars=500):
    """Sentence-aware ~max_chars chunks so each synth call is small and starts fast."""
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    chunks, cur = [], ""
    for part in re.split(r"(?<=[.!?])\s+", text):
        if not part:
            continue
        if cur and len(cur) + len(part) + 1 > max_chars:
            chunks.append(cur)
            cur = part
        else:
            cur = f"{cur} {part}".strip()
    if cur:
        chunks.append(cur)
    return chunks


def main():
    if len(sys.argv) < 3:
        return 2
    voice, work = sys.argv[1], sys.argv[2]
    with open(os.path.join(work, "text.txt"), encoding="utf-8") as fh:
        text = fh.read()
    chunks = chunk_text(text)
    if not chunks:
        return 0

    lang = voice[0] if voice[:1] in LANGS else "a"
    from kokoro import KPipeline  # heavy import — happens once
    import soundfile as sf

    pipe = KPipeline(lang_code=lang)

    q: "queue.Queue[str | None]" = queue.Queue(maxsize=4)

    def player():
        while True:
            f = q.get()
            if f is None:
                break
            subprocess.run(["afplay", f], check=False)
            try:
                os.remove(f)
            except OSError:
                pass

    t = threading.Thread(target=player, daemon=True)
    t.start()

    idx = 0
    for chunk in chunks:
        for _, _, audio in pipe(chunk, voice=voice):
            wav = os.path.join(work, f"seg_{idx}.wav")
            sf.write(wav, audio, 24000)
            if idx == 0:
                open(os.path.join(work, "ok"), "w").close()
            q.put(wav)
            idx += 1
    q.put(None)
    t.join()
    return 0


if __name__ == "__main__":
    import shutil

    code = 1
    try:
        code = main()
    finally:
        if len(sys.argv) >= 3:
            shutil.rmtree(sys.argv[2], ignore_errors=True)
    sys.exit(code)
