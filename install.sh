#!/usr/bin/env bash
# readaloud installer — sets up the Python env, the `readaloud` / `ra` shell
# aliases, and the Claude Code read-aloud skill. Idempotent: safe to re-run.
#
#   ./install.sh
#
# Paths are resolved from wherever this repo is cloned, so nothing is hardcoded.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN="$REPO_DIR/.venv/bin/readaloud"

say()  { printf '\033[1;36m▶\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!\033[0m %s\n' "$*" >&2; }

# 1. Python environment (uv) -------------------------------------------------
if ! command -v uv >/dev/null 2>&1; then
  warn "uv is required but not found."
  warn "Install it, then re-run:  curl -LsSf https://astral.sh/uv/install.sh | sh"
  exit 1
fi
say "Syncing Python environment (uv sync)…"
( cd "$REPO_DIR" && uv sync )

if [ ! -x "$BIN" ]; then
  warn "Console script not found at $BIN after 'uv sync'."
  exit 1
fi

# 2. Claude Code skill -------------------------------------------------------
SKILL_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills/read-aloud"
say "Installing the read-aloud skill → $SKILL_DIR"
mkdir -p "$SKILL_DIR"
sed "s#__READALOUD_BIN__#$BIN#g" "$REPO_DIR/skill/SKILL.md.tmpl" > "$SKILL_DIR/SKILL.md"

# 3. Shell aliases (idempotent managed block) --------------------------------
ZSHRC="${ZDOTDIR:-$HOME}/.zshrc"
MARK_START="# >>> readaloud >>>"
MARK_END="# <<< readaloud <<<"
say "Updating aliases in $ZSHRC"
touch "$ZSHRC"
# Drop any prior managed block so re-runs don't stack duplicates.
if grep -qF "$MARK_START" "$ZSHRC"; then
  tmp="$(mktemp)"
  awk -v s="$MARK_START" -v e="$MARK_END" '
    $0 == s { skip = 1 }
    skip && $0 == e { skip = 0; next }
    !skip { print }
  ' "$ZSHRC" > "$tmp" && mv "$tmp" "$ZSHRC"
fi
cat >> "$ZSHRC" <<EOF
$MARK_START
# readaloud: TUI + quick TTS for Claude Code responses / files (always warm).
#   readaloud            -> open the TUI
#   readaloud read [F]   -> read last response / a file (warm via the daemon)
#   readaloud stop|status
#   readaloud daemon --stop|--status
alias readaloud='$BIN'
alias ra='readaloud'
$MARK_END
EOF

say "Done."
echo
echo "  Restart your shell, or:  source \"$ZSHRC\""
echo "  Then:                    readaloud        # opens the TUI"
echo "                           readaloud read   # warm read of your last response"
echo "  In Claude Code:          /read-aloud"
