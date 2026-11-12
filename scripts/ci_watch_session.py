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
    # `gh run list | xargs -r gh run watch` reports success when `gh run list`
    # fails: the pipe produces no input, `xargs` exits 0, and the caller reads a
    # green "ci exit=0" from a run that was never watched. `set -o pipefail`
    # makes the failing stage fail the watch instead.
    return (
        f"set -o pipefail; cd {REPO} && {watch}; "
        f"printf '\\n=== ci exit=%s\\n' \"$?\""
    )
