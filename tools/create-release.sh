#!/usr/bin/env bash

set -euo pipefail

REMOTE="origin"
BRANCH="main"
VERSION_SCRIPT="./tools/version.py"

WORKFLOWS=(
  "Package Linux"
  "Package macOS"
  "Package Windows"
)

die() {
  echo "Error: $*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 ||
    die "Required command not found: $1"
}

find_run_id() {
  local workflow="$1"
  local commit="$2"
  local run_id=""

  for _ in $(seq 1 30); do
    run_id="$(
      gh run list \
        --workflow "$workflow" \
        --event workflow_dispatch \
        --limit 20 \
        --json databaseId,headSha,createdAt \
        --jq ".[] |
          select(.headSha == \"$commit\") |
          .databaseId" |
        head -n 1
    )"

    if [[ -n "$run_id" ]]; then
      printf '%s\n' "$run_id"
      return 0
    fi

    sleep 2
  done

  return 1
}

if [[ $# -ne 0 ]]; then
  die "This script does not accept arguments; the version is read from $VERSION_SCRIPT"
fi

require_command git
require_command gh
require_command python3

git rev-parse --is-inside-work-tree >/dev/null 2>&1 ||
  die "Run this script inside the Git repository"

REPOSITORY_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPOSITORY_ROOT"

if [[ ! -f "$VERSION_SCRIPT" ]]; then
  die "Version script not found: $VERSION_SCRIPT"
fi

VERSION="$(python3 "$VERSION_SCRIPT" --read)" ||
  die "Failed to read the application version"

if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][0-9A-Za-z.-]+)?$ ]]; then
  die "Invalid version returned by $VERSION_SCRIPT: $VERSION"
fi

TAG="v$VERSION"


gh auth status >/dev/null 2>&1 ||
  die "GitHub CLI is not authenticated; run: gh auth login"

CURRENT_BRANCH="$(git branch --show-current)"

if [[ "$CURRENT_BRANCH" != "$BRANCH" ]]; then
  die "Current branch is '$CURRENT_BRANCH'; switch to '$BRANCH' first"
fi

if [[ -n "$(git status --porcelain)" ]]; then
  die "Working tree is not clean; commit or stash changes first"
fi

echo "Fetching $REMOTE/$BRANCH..."
git fetch "$REMOTE" "$BRANCH" --tags

LOCAL_COMMIT="$(git rev-parse HEAD)"
REMOTE_COMMIT="$(git rev-parse "$REMOTE/$BRANCH")"

if [[ "$LOCAL_COMMIT" != "$REMOTE_COMMIT" ]]; then
  die "Local HEAD differs from $REMOTE/$BRANCH; push or pull first"
fi

if git rev-parse "$TAG" >/dev/null 2>&1; then
  die "Local tag already exists: $TAG"
fi

if git ls-remote --exit-code --tags "$REMOTE" \
  "refs/tags/$TAG" >/dev/null 2>&1; then
  die "Remote tag already exists: $TAG"
fi

echo
echo "Release target:"
echo "  Tag:    $TAG"
echo "  Commit: $LOCAL_COMMIT"
echo "  Branch: $BRANCH"
echo

read -r -p "Create and push this tag? [y/N] " answer

case "$answer" in
  y|Y|yes|YES)
    ;;
  *)
    echo "Cancelled."
    exit 0
    ;;
esac

echo "Creating annotated tag..."
git tag -a "$TAG" -m "Flowdesk $TAG"

echo "Pushing tag..."
git push "$REMOTE" "$TAG"

declare -A RUN_IDS

for workflow in "${WORKFLOWS[@]}"; do
  echo
  echo "Dispatching: $workflow"
  gh workflow run "$workflow" --ref "$TAG"

  run_id="$(find_run_id "$workflow" "$LOCAL_COMMIT")" ||
    die "Could not find workflow run for: $workflow"

  RUN_IDS["$workflow"]="$run_id"
  echo "Run ID: $run_id"
done

echo
echo "Waiting for workflows..."

for workflow in "${WORKFLOWS[@]}"; do
  run_id="${RUN_IDS[$workflow]}"

  echo
  echo "Watching: $workflow ($run_id)"

  if ! gh run watch "$run_id" --exit-status; then
    echo
    echo "Workflow failed: $workflow"
    echo "Inspect it with:"
    echo "  gh run view $run_id --web"
    exit 1
  fi
done

DOWNLOAD_DIR="release-work/$TAG"
ASSET_DIR="$DOWNLOAD_DIR/assets"

rm -rf "$DOWNLOAD_DIR"
mkdir -p "$ASSET_DIR"

for workflow in "${WORKFLOWS[@]}"; do
  run_id="${RUN_IDS[$workflow]}"
  slug="$(
    printf '%s' "$workflow" |
      tr '[:upper:]' '[:lower:]' |
      tr ' ' '-'
  )"

  echo
  echo "Downloading artifacts: $workflow"
  gh run download "$run_id" \
    --dir "$DOWNLOAD_DIR/$slug"
done

echo
echo "Downloaded files:"
find "$DOWNLOAD_DIR" -type f -print

while IFS= read -r -d '' file; do
  filename="$(basename "$file")"
  destination="$ASSET_DIR/$filename"

  if [[ -e "$destination" ]]; then
    die "Duplicate release asset filename: $filename"
  fi

  cp -a "$file" "$destination"
done < <(
  find "$DOWNLOAD_DIR" \
    -path "$ASSET_DIR" -prune -o \
    -type f \
    \( \
      -name '*.zip' -o \
      -name '*.tar.gz' -o \
      -name '*.tgz' -o \
      -name '*.dmg' -o \
      -name '*.AppImage' \
    \) \
    -print0
)

mapfile -d '' RELEASE_ASSETS < <(
  find "$ASSET_DIR" \
    -maxdepth 1 \
    -type f \
    -print0 |
    sort -z
)

if [[ ${#RELEASE_ASSETS[@]} -eq 0 ]]; then
  die "No release-ready archive files were found"
fi

echo
echo "Release assets:"

printf '  %s\n' "${RELEASE_ASSETS[@]}"

echo
echo "Creating draft release..."

gh release create "$TAG" \
  "${RELEASE_ASSETS[@]}" \
  --verify-tag \
  --title "Flowdesk $TAG" \
  --generate-notes \
  --draft

echo
echo "Draft release created:"
gh release view "$TAG" --json url --jq '.url'

echo
echo "Review it in the browser:"
echo "  gh release view $TAG --web"
