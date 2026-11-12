#!/usr/bin/env bash
# Keep bugwatch running: restart it if it dies, and record a heartbeat so its
# liveness is checkable. Start it detached (setsid) so it outlives the shell
# that launched it:
#
#   setsid nohup script/bugwatch-supervisor.sh /home/deadbeef/github/dashboard \
#       >/dev/null 2>&1 </dev/null &
#
# bugwatch itself exits on the first event (so a caller can act on it); this
# supervisor restarts it, which is what makes it a standing watcher rather than
# a one-shot.
set -u
DIR="${1:-/home/deadbeef/github/dashboard}"
LOG="${BUGWATCH_LOG:-/tmp/bugwatch.log}"
HB="${BUGWATCH_HEARTBEAT:-/tmp/bugwatch.supervisor}"
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
while true; do
    date +%s > "$HB" 2>/dev/null || true
    python3 "$SELF_DIR/bugwatch.py" "$DIR" --follow >>"$LOG" 2>&1
    printf '%s bugwatch exited rc=%s; restarting\n' "$(date -Is)" "$?" >>"$LOG"
done
