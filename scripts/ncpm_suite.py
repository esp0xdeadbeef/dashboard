#!/usr/bin/env python3
"""Run the network-control-plane-model suite on a remote host, one pane.

The suite takes ~30 minutes, so the caller must not poll it. One `spawn_*`
gives one session with one pane; the pane runs the suite plus the exit-status
line the dashboard convention expects, and a caller blocks with
`wait_pane_idle(compat.pane_by_id(pid))`.

Environment:
    SUITE_HOST   host to run on (default 100.64.0.13)
    SUITE_DIR    checkout on that host
                 (default /tmp/ncpmws/network-control-plane-model)
    SUITE_OUT    log file on that host (default /tmp/suite-dash.out)
"""

import os

HOST = os.environ.get("SUITE_HOST", "100.64.0.13")
DIR = os.environ.get(
    "SUITE_DIR", "/tmp/ncpmws/network-control-plane-model")
OUT = os.environ.get("SUITE_OUT", "/tmp/suite-dash.out")


def spawn_suite():
    """Stream the suite result in one pane."""
    session = renew_session("suite")
    panes_from_list(
        session,
        [_suite_command()],
        start_directory=os.path.expanduser("~"),
    )


def _suite_command():
    inner = (
        f"cd {DIR} && "
        f"NETWORK_REPO_DIRECT_TEST_OK=1 ./run-all-tests.sh > {OUT} 2>&1; "
        f"grep -E '^Results:' {OUT} || tail -5 {OUT}"
    )
    # wait_pane_idle returns the command's whole output block (not one line), so
    # the trailing SUITE_EXIT= is a convenience for a human reader and for
    # parsing, not a requirement of the primitive.
    return (
        f"ssh -o BatchMode=yes {HOST} {inner!r}; "
        f"echo SUITE_EXIT=$?"
    )
