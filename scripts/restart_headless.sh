#!/usr/bin/env bash
# Restart the headless Blender session with the current add-on source.
#
# `pkill -f <pattern>` is avoided on purpose: the pattern would match this
# script's own command line and kill the calling shell.
set -uo pipefail

REPO=/root/blender-mcp
PORT="${1:-9877}"
LOG=/root/.hermes/cache/blender-mcp-headless.log

for pid in $(pgrep -f "[b]lender --background" || true); do
  kill "$pid" 2>/dev/null || true
done
sleep 1

: > "$LOG"
cd "$REPO" || exit 1
.venv/bin/python -m blender_mcp install >/dev/null || exit 1
.venv/bin/python -m blender_mcp headless --port "$PORT" --log "$LOG" || exit 1

for _ in $(seq 1 20); do
  sleep 1
  if .venv/bin/python -m blender_mcp doctor --port "$PORT" 2>/dev/null | grep -q "add-on server reachable"; then
    echo "blender-mcp headless ready on $PORT"
    cat "$LOG"
    exit 0
  fi
done

echo "TIMED OUT waiting for the add-on server on $PORT"
cat "$LOG"
exit 1
