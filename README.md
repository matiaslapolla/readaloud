# readaloud

A terminal text-to-speech tool that reads your **last Claude Code response** (or any
file) out loud, with natural neural voices. Today it's a set of shell scripts; the goal
is to grow it into a full **TUI app**.

## Status

🌱 **Pre-design.** A working prototype lives in [`reference/`](./reference) (the scripts
currently installed as a Claude Code skill at `~/.claude/skills/read-aloud/`). The TUI
architecture (language/framework, features) is **still to be decided** — see
[`docs/HANDOFF.md`](./docs/HANDOFF.md) for the full context, what works, and the long
list of macOS/TTS gotchas already solved.

## What the prototype does

- Reads the **previous assistant response** from the active session's transcript, or a
  **file** you pass it.
- Strips markdown/code/tags, then speaks it via one of three engines (auto-fallback):
  - **kokoro** (default) — local/offline neural model, private.
  - **edge** — Microsoft neural voices (needs internet, faster start).
  - **say** — macOS built-in (offline, robotic) — last-resort fallback.
- **Streams**: chunks text at sentence boundaries and plays chunk N while synthesizing
  N+1, so long docs start in seconds instead of after the whole render.
- Random voice per run; `stop` cancels; self-cleaning temp files.

```bash
# current prototype (from reference/, or via the `readaloud` zsh alias)
readaloud                       # last response
readaloud ./some-file.md        # a file
readaloud stop
```

## Where we're headed (to discuss)

A proper TUI: live playback queue, voice/engine picker, history of past reads,
pause/resume/scrub, a warm Kokoro daemon for instant local starts, persisted settings.
Stack is open — see the handoff doc.
