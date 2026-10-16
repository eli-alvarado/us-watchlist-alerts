#!/usr/bin/env bash
# Publish one docs/live/YYYY-MM-DD.md to $LIVE_BRANCH (default live-snapshots).
# Never commits or pushes main / master / the remote default branch.
set -euo pipefail

FILE="${1:?usage: publish_live_snapshot.sh docs/live/YYYY-MM-DD.md}"
LIVE_BRANCH="${LIVE_BRANCH:-live-snapshots}"
REMOTE="${LIVE_REMOTE:-origin}"

default="main"
if git symbolic-ref -q "refs/remotes/${REMOTE}/HEAD" >/dev/null 2>&1; then
  default="$(git symbolic-ref --short "refs/remotes/${REMOTE}/HEAD")"
  default="${default#${REMOTE}/}"
fi

case "$LIVE_BRANCH" in
  main|master|"$default")
    echo "refusing to publish onto default branch ${LIVE_BRANCH}" >&2
    exit 2
    ;;
esac

if [ ! -f "$FILE" ]; then
  echo "missing $FILE" >&2
  exit 1
fi

git fetch "$REMOTE" "$LIVE_BRANCH" || true

git config user.name "${GIT_AUTHOR_NAME:-github-actions[bot]}"
git config user.email "${GIT_AUTHOR_EMAIL:-41898282+github-actions[bot]@users.noreply.github.com}"

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT
cp "$FILE" "$tmpdir/snap.md"

if git show-ref --verify --quiet "refs/heads/${LIVE_BRANCH}"; then
  git checkout "${LIVE_BRANCH}"
elif git rev-parse --verify -q "${REMOTE}/${LIVE_BRANCH}" >/dev/null; then
  git checkout -B "${LIVE_BRANCH}" "${REMOTE}/${LIVE_BRANCH}"
elif git rev-parse --verify --quiet HEAD >/dev/null; then
  # First publish: branch from current HEAD (usually main) without committing here.
  git checkout -B "${LIVE_BRANCH}"
else
  git checkout --orphan "${LIVE_BRANCH}"
fi

head="$(git rev-parse --abbrev-ref HEAD)"
if [ "$head" = "main" ] || [ "$head" = "master" ] || [ "$head" = "$default" ]; then
  echo "still on ${head}; abort" >&2
  exit 2
fi

mkdir -p "$(dirname "$FILE")"
cp "$tmpdir/snap.md" "$FILE"
git add -- "$FILE"
if git diff --cached --quiet; then
  echo "no change on ${LIVE_BRANCH}"
  exit 0
fi
git commit -m "docs(live): weekday snapshot"
# Explicit dest ref — never a bare `git push`, never :main
git push "$REMOTE" "HEAD:refs/heads/${LIVE_BRANCH}"
echo "published ${FILE} to ${REMOTE}/${LIVE_BRANCH}"
