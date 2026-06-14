---
name: read-aloud
description: Read the previous assistant response aloud using macOS text-to-speech. Use when the user types /read-aloud, or asks to "read that out loud", "say it", "speak the last response", or wants a prompt/standup/answer narrated while they do something else. Supports "stop" to cancel narration.
---

# read-aloud

Speak the **previous assistant message** aloud via macOS `say`. The companion script
pulls the last text response straight from the live session transcript, so the user
does not need to paste or re-type anything.

## How to run it

Do this with **no preamble text** — the very first thing in your turn must be the Bash
call below. Emitting text first would make *your current message* the "last response"
and it would read itself back. Just run the script.

- Read last response: ``bash ~/.claude/skills/read-aloud/read-aloud.sh``
- Read a file: ``bash ~/.claude/skills/read-aloud/read-aloud.sh "<path>"``
  (use when the user names a file/doc to narrate, e.g. "read aloud spec.md".
  Quote the path; ``~`` is supported; relative paths resolve from the project dir.)
  IMPORTANT: if the user references the file with an ``@``-mention (e.g.
  ``@clipchum/.claude/prompts/foo.md``), the harness expands that into the file's
  *contents*, NOT a path — so you must pass the **literal file path** as the
  argument (drop the ``@``), e.g.
  ``bash ~/.claude/skills/read-aloud/read-aloud.sh "clipchum/.claude/prompts/foo.md"``.
  Do not paste the file contents into the command.
- Stop playback: ``bash ~/.claude/skills/read-aloud/read-aloud.sh stop``
  (use when the user says "stop", "quiet", "cancel reading")

The script prints a one-line status. Relay it tersely (e.g. "▶️ Reading the last
response aloud (Samantha)."). Do not re-narrate the content yourself.

## Engine & voice

Engines (``READ_ALOUD_ENGINE``), each streamed chunk-by-chunk, random voice per run:
- **edge** (default): Microsoft neural voices. Natural, free, **needs internet**;
  ~2-3s to first audio. Text is sent to Microsoft.
- **kokoro**: fully **local/offline** neural model (private). Natural, but ~8-13s to
  first audio (loads the model per run). Needs ``uv`` + one-time model download.
- **say**: macOS built-in, offline, robotic. Automatic fallback if edge/kokoro fail.

- Pick engine: ``READ_ALOUD_ENGINE=kokoro bash ~/.claude/skills/read-aloud/read-aloud.sh``
- Pin a voice: edge ``READ_ALOUD_VOICE=en-US-AvaMultilingualNeural``; kokoro
  ``READ_ALOUD_VOICE=af_heart`` (Spanish: ``ef_dora``); say ``READ_ALOUD_VOICE="Evan (Enhanced)"``.
- Speed: ``READ_ALOUD_EDGE_RATE=+15%`` (edge) or ``READ_ALOUD_RATE=240`` (say, wpm).

## Notes

- Code fences and inline code are stripped before speaking, so code blocks are
  skipped rather than read symbol-by-symbol.
- Narration runs in the background; the session stays responsive and a new
  ``/read-aloud`` interrupts the prior one.
