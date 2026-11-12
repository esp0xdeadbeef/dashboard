#!/usr/bin/env python3
"""Run a CI watch in a pane and block until it really finishes.

Exercises `checked_cmd`, the dashboard primitive that sends a command and waits
for its end marker. That is the right primitive here: `wait_pane_idle` alone
returns on the first idle sample, which for a freshly spawned pane is the shell
*before* the command has started, so it reports "finished" immediately.

Environment:
    CI_WATCH_REPO  checkout to watch (default ~/github/network-labs)
    CI_WATCH_ID    run id (default: newest run of that repo)
"""

import os

REPO = os.environ.get("CI_WATCH_REPO", os.path.expanduser("~/github/network-labs"))
RUN_ID = os.environ.get("CI_WATCH_ID", "")


def spawn_ciwait():
    """Watch a CI run with checked_cmd and print the tail once it finishes."""
    session = renew_session("ciwait")
    # Seed the pane with a no-op so the window exists; checked_cmd then
    # types its own line at the prompt. A real command here would be
    # concatenated with checked_cmd's line, as `truecd ...` showed.
    panes_from_list(session, [""], start_directory=REPO)
    pane = compat.active_pane(session)

    checked_cmd(
        pane,
        _watch_command(),
        last_row_send="",
        complete_timeout=5400,
    )

    lines = compat.capture_pane(pane, start=-40) or []
    tail = [line for line in lines if line.strip()][-25:]
    print("\n".join(tail))


def _watch_command():
    # `gh run list | xargs -r gh run watch` reports success when `gh run list`
    # fails: the pipe produces no input, `xargs` exits 0, and the caller reads a
    # green "ci exit=0" from a run that was never watched. `set -o pipefail`
    # makes the failing stage fail the watch instead.
    if RUN_ID:
        watch = f"gh run watch {RUN_ID} --exit-status"
    else:
        watch = ("gh run list --limit 1 --json databaseId "
                 "--jq '.[0].databaseId' | xargs -r gh run watch --exit-status")
    return f"set -o pipefail; cd {REPO} && {watch}; printf '\\n=== ci exit=%s\\n' \"$?\""
