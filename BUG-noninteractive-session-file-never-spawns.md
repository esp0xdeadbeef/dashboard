# BUG: non-interactive `--session-file` never spawns; it requires a session it never created

**Severity:** HIGH — the documented unattended mode (the one CI and agents are
told to use) cannot create a session at all.
**File:** `main_tdashboard.py` (`s_all`, and the non-interactive branch of
`main`)
**Status:** OPEN

## Symptom

The README's "Running a session file unattended (no REPL)" section says:

> Drop `-i`: the dashboard spawns every `spawn_*` in the session file and
> returns.

It does not spawn. `main()` ends with:

```python
    if args.interactive:
        interactive_dashboard(session_functions, debugging=True)
    else:
        s_all(respawn_all=False)
```

and `s_all(respawn_all=False)` takes the *attach* branch, not the spawn branch:

```python
        else:
            print(f"Trying to get active_pane of {name}")
            try:
                name_pane = compat.active_pane(
                    compat.require_session(server, name))
```

So on a target with no matching session yet, the run prints
`dashboard: no tmux session named '<name>'` and
`Trying to get active_pane of <name>`, creates nothing, and exits 0 — a
silently empty success.

If a session *does* exist under that name but was created by anything else (a
plain `tmux new-session -d -s <name>`, for example) the same branch then fails
with `can't find window: w`, because the session it attached to has no window
named after the session file's window.

## Exact reproduction

Target: any reachable host, here `100.64.0.17` (s-tau).

```
$ cat /tmp/wgci/probe.py
import compat

def spawn_probe():
    session = renew_session("probe")
    window = compat.new_window_named(session, "w")
    pane = compat.active_pane_of_window(window)
    compat.send_keys(pane, "echo HELLO_PROBE; uname -n")
    compat.send_keys(pane, "C-m")

$ cd ~/github/dashboard
$ venv/bin/python main_tdashboard.py --target 100.64.0.17 /tmp/wgci \
      --session-file /tmp/wgci/probe.py
dashboard: no tmux session named 'probe'
dashboard: target 100.64.0.17 via ssh 100.64.0.17  (host s-tau)
Trying to get active_pane of probe
$ echo $?
0
$ ssh 100.64.0.17 'tmux list-sessions'
no server running on /tmp/tmux-1000/default
```

Nothing was created, and the exit status says success. `HELLO_PROBE` never runs.

Pre-creating the session changes the failure, not the outcome:

```
$ ssh 100.64.0.17 'tmux new-session -d -s probe "zsh -i"'
$ venv/bin/python main_tdashboard.py --target 100.64.0.17 /tmp/wgci \
      --session-file /tmp/wgci/probe.py
dashboard: target 100.64.0.17 via ssh 100.64.0.17  (host s-tau)
Trying to get active_pane of probe
can't find window: w
```

## Why it matters

This is the only form that works without a TTY, so it is the form CI and agents
use — and it is the form the goal contract points at ("USE the dashboard instead
of using sleeps"). A caller that trusts the exit code concludes the work ran
when no pane was ever created. An interactive session masking the bug makes it
worse: if a stale session with the right name happens to exist, the run
"passes" without executing the new session file at all.

## Expected

Non-interactive mode should call the spawn path
(`s_all(respawn_all=True)`, i.e. the `interactive_dashboard` side effect
without the REPL) so every `spawn_*` in the session file is created, and should
exit non-zero when a `spawn_*` it was asked to run could not be reached
afterwards. The `no tmux session named '<x>'` notice printed before a *spawn* is
expected (see `BUG-6003660b-…`); printing it while also refusing to spawn is
not.

## Verified on

Linux, `tmux 3.7b` on the remote target, `venv/bin/python` 3.13, dashboard
checkout at `~/github/dashboard`.
