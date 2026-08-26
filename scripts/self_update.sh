#!/usr/bin/env bash
# Checks for and applies updates from the git remote before launching.
# Sourced by start.sh/start-bot.sh (not run directly) - the caller must
# already have cd'd to the repo root.

if [ ! -d .git ]; then
    exit 0
fi

if [ -n "$(git status --porcelain)" ]; then
    echo "self_update: local changes present - skipping auto-update, starting with the code as-is."
    exit 0
fi

echo "self_update: checking for updates..."
if ! git fetch --quiet origin 2>/dev/null; then
    echo "self_update: couldn't reach the remote (offline?) - starting with the code as-is."
    exit 0
fi

LOCAL_COMMIT=$(git rev-parse HEAD)
REMOTE_COMMIT=$(git rev-parse '@{u}' 2>/dev/null)

if [ -z "$REMOTE_COMMIT" ]; then
    echo "self_update: no upstream branch configured - skipping."
    exit 0
fi

if [ "$LOCAL_COMMIT" = "$REMOTE_COMMIT" ]; then
    echo "self_update: already up to date."
    exit 0
fi

echo "self_update: update available - pulling..."
if ! git pull --ff-only --quiet; then
    # Only ever fast-forwards - if the branch has diverged (e.g. local
    # commits that aren't on the remote), this refuses rather than merging
    # or discarding anything, and startup just continues on the old code.
    echo "self_update: pull wasn't a fast-forward (local branch has diverged?) - starting with the code as-is."
    exit 0
fi

echo "self_update: updated to $(git rev-parse --short HEAD)."

if ! git diff --quiet "$LOCAL_COMMIT" HEAD -- requirements.txt; then
    echo "self_update: requirements.txt changed - reinstalling dependencies..."
    .venv/bin/pip install -q -r requirements.txt
fi
