#!/bin/sh
# Link Project 02 skills into the local Hermes skills directory.
set -eu
ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
TEAMS="$(CDPATH= cd -- "$ROOT/.." && pwd)"
DEST="${HERMES_SKILLS:-$HOME/.hermes/skills}/aveyroni"
mkdir -p "$DEST"
link() {
  name="$(basename "$1")"
  ln -sfn "$1" "$DEST/$name"
  echo "linked $name"
}
for dir in "$ROOT"/skills/* "$TEAMS"/shared/*; do
  if [ -f "$dir/SKILL.md" ]; then
    link "$dir"
  fi
done
echo "Installed into $DEST"
echo "Start a new Hermes session before expecting these skills to appear."
