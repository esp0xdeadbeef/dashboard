#!/usr/bin/env bash
# Keep bugwatch running, and keep a heartbeat that proves it is alive.
#
# Start it detached so it outlives the shell that launched it:
#   setsid nohup scripts/bugwatch-supervisor.sh <dir> >/dev/null 2>&1 </dev/null &
#
# bugwatch exits on the first event (so a caller can act on it); this supervisor
# restarts it, which is what makes it a standing watcher rather than a one-shot.
# The heartbeat is written by a separate loop: an earlier version only touched it
# when the inner watcher exited, so while the watcher ran normally the heartbeat
# froze and looked dead (measured 1891s stale).
set -u
DIR="${1:-/home/deadbeef/github/dashboard}"
LOG="${BUGWATCH_LOG:-/tmp/bugwatch.log}"
HB="${BUGWATCH_HEARTBEAT:-/tmp/bugwatch.supervisor}"
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

heartbeat() {
    while true; do
        date +%s > "$HB" 2>/dev/null || true
        sleep 30
    done
}
heartbeat &
HB_PID=$!
trap 'kill "$HB_PID" 2>/dev/null' EXIT INT TERM

while true; do
    python3 "$SELF_DIR/bugwatch.py" "$DIR" --follow >>"$LOG" 2>&1
    printf '%s bugwatch exited rc=%s; restarting\n' "$(date -Is)" "$?" >>"$LOG"
done
