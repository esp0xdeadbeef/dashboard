#!/usr/bin/env python3
"""Run the repository suite in one pane, with its exit status recorded.

Unlike a CI watcher this pane runs the suite itself, so the exit status is
available in the pane (`=== suite exit=<n>`) without depending on gh.
"""

import os

REPO = os.environ.get("SUITE_REPO", os.path.expanduser("~/github/network-labs"))


def spawn_suite():
    session = renew_session("suite")
    panes_from_list(
        session,
        [
            f"cd {REPO} && "
            f"NETWORK_REPO_DIRECT_TEST_OK=1 ./run-all-tests.sh; "
            f"printf '\\n=== suite exit=%s\\n' \"$?\""
        ],
        start_directory=REPO,
    )
