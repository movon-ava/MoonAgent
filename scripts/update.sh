#!/usr/bin/env bash
# One-click update (Linux / macOS).
#
#   bash scripts/update.sh              # pull + uv sync
#   bash scripts/update.sh --rebuild    # also rebuild the sandbox image
#   bash scripts/update.sh --no-deps    # code only
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

REBUILD=0
DEPS=1
for arg in "$@"; do
  case "$arg" in
    --rebuild) REBUILD=1 ;;
    --no-deps) DEPS=0 ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg"; exit 2 ;;
  esac
done

echo "== CTF Agent update =="
echo "repo: $ROOT"

if [ ! -d .git ]; then
  echo "not a git checkout - re-clone the repository instead" >&2
  exit 1
fi

if [ -f .env ]; then
  cp .env .env.bak
  echo "[1/4] backed up .env -> .env.bak"
else
  echo "[1/4] no .env yet (copy .env.example after the update)"
fi

git fetch --prune
if [ -n "$(git status --porcelain)" ]; then
  echo "local changes detected:" >&2
  git status --short >&2
  echo "run 'git stash' first, then re-run this script" >&2
  exit 1
fi
git pull --ff-only
echo "[2/4] code updated"

if [ "$DEPS" -eq 1 ]; then
  if ! command -v uv >/dev/null 2>&1; then
    echo "uv not found - install: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
    exit 1
  fi
  uv sync
  echo "[3/4] python dependencies synced"
else
  echo "[3/4] skipped dependency sync (--no-deps)"
fi

if [ "$REBUILD" -eq 1 ]; then
  if ! command -v docker >/dev/null 2>&1; then
    echo "docker not found" >&2
    exit 1
  fi
  echo "[4/4] rebuilding ctf-sandbox (this takes a while)..."
  docker build -f sandbox/Dockerfile.sandbox -t ctf-sandbox .
else
  echo "[4/4] skipped image rebuild (pass --rebuild to do it)"
fi

echo
echo "done. your previous .env is at .env.bak (merge any new keys by hand)."
echo "start the dashboard: uv run python scripts/webui.py --port 8099"
