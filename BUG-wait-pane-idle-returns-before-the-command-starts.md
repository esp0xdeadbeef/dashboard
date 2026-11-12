# BUG-wait-pane-idle-returns-before-the-command-starts

`wait_pane_idle()` reports "finished" for a pane whose command has not started.

## Reproduced

```python
session = renew_session("ci")
panes_from_list(session, [_watch_command()], start_directory=REPO)
pane = compat.active_pane(session)
compat.wait_pane_idle(pane)          # returns in ~0s
```

Expected: block until `gh run watch` exits.
Actual: returns immediately, and the captured tail is the typed command still
sitting at the prompt, unexecuted:

```
└─[%] cd /home/deadbeef/github/network-labs && gh run watch 43320670072 --exit-s
tatus; printf '\n=== ci exit=%s\n' "$?"
```

The command only ran after an extra `tmux send-keys -t ci Enter`.

## Why

`wait_pane_idle` returns on the **first** sample where `at_end()` is true
(`main_tdashboard.py:968-980`). It waits for the pane to *be* idle; it never
requires the pane to first become busy. Immediately after `panes_from_list()`,
the shell is idle, so the first sample satisfies the predicate.

This is stated as a known hazard for the *reverse* case in `checked_cmd`'s
comment ("it is ready the instant the line is sent, before the command has run
at all"), but `wait_pane_idle` has no equivalent guard, and its docstring
advertises exactly the pattern that trips it:

> a caller blocks with `wait_pane_idle(compat.pane_by_id(pid))`
> -- `scripts/ci_watch_session.py`

## Suggested fix (either)

1. Make `wait_pane_idle` require one busy sample before it will accept an idle
   one, with a bounded grace period for commands that finish instantly; or
2. Have the `spawn_*` helpers return the pane **after** observing it busy, so
   `wait_pane_idle` cannot be raced; or
3. Document in `ci_watch_session.py` that the caller must use `checked_cmd`
   (which appends an end marker) rather than `wait_pane_idle`.

`scripts/ci_wait_session.py` in this repo now uses `checked_cmd` and blocks
correctly; it exists as the working reference for case (3).

## Severity

Silent wrong answer: a long CI run is reported as already finished, and the
caller reads a tail that contains no result. Not an error, so nothing prompts a
retry.
