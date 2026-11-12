#!/usr/bin/env python3
"""Watch the newest CI run for a repository.

One `spawn_*` gives one session with one pane; the pane runs `gh run watch`,
which streams the run's own progress. The spawner returns immediately, and a
caller blocks with `wait_pane_idle(compat.pane_by_id(pid))`.

Environment:
    CI_WATCH_REPO   checkout to watch (default ~/github/network-renderer-nixos)
    CI_WATCH_ID     run id (default: newest run of that repo)
"""

import os

REPO = os.environ.get(
    "CI_WATCH_REPO", os.path.expanduser("~/github/network-renderer-nixos"))
RUN_ID = os.environ.get("CI_WATCH_ID", "")


def spawn_ci():
    """Stream the newest CI run in one pane."""
    session = renew_session("ci")
    panes_from_list(
        session,
        [_watch_command()],
        start_directory=REPO,
    )


def _watch_command():
    if RUN_ID:
        watch = f"gh run watch {RUN_ID} --exit-status"
    else:
        watch = ("gh run list --limit 1 --json databaseId "
                 "--jq '.[0].databaseId' | xargs -r gh run watch --exit-status")
    return (
        f"cd {REPO} && {watch}; "
        f"printf '\\n=== ci exit=%s\\n' \"$?\""
    )
