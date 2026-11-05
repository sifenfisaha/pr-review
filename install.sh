#!/usr/bin/env bash
# Links this checkout into Claude Code's personal skills folder, so `git pull` updates the installed skill.
# usage: ./install.sh                       (installs to ~/.claude/skills/pr-review)
#        CLAUDE_SKILLS_DIR=/path ./install.sh
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
DEST="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}/pr-review"

missing=0
for tool in git gh python3; do
  command -v "$tool" >/dev/null 2>&1 || { echo "missing: $tool" >&2; missing=1; }
done
if [ "$missing" = 1 ]; then
  echo "install the tools above and rerun. gh: https://cli.github.com" >&2
  exit 1
fi
if ! gh auth status >/dev/null 2>&1; then
  echo "note: the GitHub CLI is not logged in. Run 'gh auth login' before reviewing GitHub pull requests; local branch reviews work without it." >&2
fi

mkdir -p "$(dirname "$DEST")"
if [ -e "$DEST" ] && [ ! -L "$DEST" ]; then
  echo "$DEST already exists and is not a symlink; move it aside and rerun" >&2
  exit 1
fi
ln -sfn "$HERE" "$DEST"
chmod +x "$HERE"/scripts/*
echo "linked $DEST -> $HERE"
echo "installed. Start a new Claude Code session and run:  /pr-review <PR number or URL>"
