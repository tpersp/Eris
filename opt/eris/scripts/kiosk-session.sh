#!/usr/bin/env bash
set -euo pipefail

export DISPLAY="${DISPLAY:-:0}"

# Give X a moment to finish initialising before issuing xset commands.
sleep 0.5

if command -v xset >/dev/null 2>&1; then
  xset -dpms || true
  xset s off || true
  xset s noblank || true
fi

if command -v matchbox-window-manager >/dev/null 2>&1; then
  exec matchbox-window-manager -use_titlebar no -use_cursor no
elif command -v openbox >/dev/null 2>&1; then
  exec openbox
elif command -v fluxbox >/dev/null 2>&1; then
  exec fluxbox
else
  echo "Warning: no lightweight window manager found; X session will terminate." >&2
  exec sleep infinity
fi
