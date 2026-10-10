#!/usr/bin/env bash
# Save a git bundle and a dependency-free source snapshot to the shared project folder.
set -euo pipefail
cd "$(dirname "$0")/.."
DEST=/mnt/project-files/trading-journal
mkdir -p "$DEST"
git bundle create "$DEST/edgeledger.bundle" --all
rm -rf "$DEST/source"
mkdir -p "$DEST/source"
git ls-files -z | xargs -0 -I{} cp --parents {} "$DEST/source/"
git log --oneline -1 > "$DEST/LAST_COMMIT.txt"
